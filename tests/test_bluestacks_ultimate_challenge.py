"""Offline visual and operator-contract checks for Ultimate Challenge Daily."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from scripts import bluestacks_ultimate_challenge as ultimate
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts import flow_delivery_ultimate_challenge_bluestacks as delivery
from scripts.flow_delivery_evidence import require_operator_evidence
from tasks.home_nav_recognition import recognize_home_nav
from tasks.ultimate_challenge_daily import (
    FLOW_ID,
    ULTIMATE_CHALLENGE_ENTRY_IDENTITY,
    UltimateChallengeEntryObservation,
    empty_reset_window_state,
)


ROOT = Path(__file__).resolve().parents[1]


class UltimateChallengeVisualTests(unittest.TestCase):
    @staticmethod
    def _main_frame(title: str = "Ultimate Challenge") -> np.ndarray:
        """Build a native frame with independently measured main-screen geometry."""
        frame = np.full((1280, 800, 3), (24, 28, 36), dtype=np.uint8)
        cv2.putText(
            frame,
            title,
            (170, 58),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.25,
            (255, 255, 255),
            3,
            cv2.LINE_AA,
        )
        cv2.rectangle(frame, (280, 1170), (520, 1260), (0, 0, 220), -1)
        return frame

    @staticmethod
    def _active_battle_frame() -> np.ndarray:
        """Build a native frame with an independently measured puzzle board."""
        frame = np.full((1280, 800, 3), (24, 28, 36), dtype=np.uint8)
        for row in range(4):
            for column in range(5):
                x0 = 55 + column * 135
                y0 = 540 + row * 105
                cv2.rectangle(
                    frame,
                    (x0, y0),
                    (x0 + 55, y0 + 55),
                    (0, 180, 255),
                    -1,
                )
        cv2.rectangle(frame, (700, 20), (750, 75), (255, 255, 255), -1)
        return frame

    @staticmethod
    def _flee_warning_frame(
        *,
        extra_panel: bool = False,
        text: str = "Flee now: failure",
    ) -> np.ndarray:
        """Build a native warning modal with independently measured geometry."""
        frame = np.full((1280, 800, 3), (24, 28, 36), dtype=np.uint8)
        cv2.rectangle(frame, (60, 360), (740, 750), (48, 48, 48), -1)
        cv2.rectangle(frame, (60, 360), (740, 750), (220, 220, 220), 12)
        cv2.rectangle(frame, (72, 372), (728, 435), (0, 0, 180), -1)
        cv2.putText(
            frame,
            text,
            (180, 535),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.15,
            (255, 255, 255),
            3,
            cv2.LINE_AA,
        )
        cv2.rectangle(frame, (100, 600), (330, 700), (0, 0, 220), -1)
        cv2.rectangle(frame, (470, 600), (700, 700), (0, 180, 220), -1)
        if extra_panel:
            cv2.rectangle(frame, (5, 20), (795, 320), (180, 180, 180), 12)
        return frame

    @staticmethod
    def _shop_like_frame() -> np.ndarray:
        """Build a non-Home shop surface without copying the Home nav template."""
        frame = np.full((1280, 800, 3), (35, 45, 65), dtype=np.uint8)
        cv2.rectangle(frame, (80, 120), (720, 1160), (35, 45, 65), -1)
        cv2.rectangle(frame, (120, 180), (680, 260), (25, 150, 210), -1)
        cv2.putText(
            frame,
            "Resource Shop",
            (190, 235),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255),
            3,
            cv2.LINE_AA,
        )
        cv2.rectangle(frame, (140, 360), (360, 520), (40, 170, 210), -1)
        cv2.rectangle(frame, (440, 360), (660, 520), (40, 170, 210), -1)
        cv2.rectangle(frame, (120, 1213), (680, 1280), (20, 20, 20), -1)
        return frame

    def test_real_production_recognizers_accept_deterministic_native_frames(self) -> None:
        main = ultimate._recognize_ultimate_main(self._main_frame())
        self.assertIsNotNone(main)
        self.assertTrue(280 <= main[0] < main[2] <= 520)
        self.assertTrue(1170 <= main[1] < main[3] <= 1260)

        active = ultimate._recognize_active_battle(self._active_battle_frame())
        self.assertIsNotNone(active)
        self.assertTrue(700 <= active[0] < active[2] <= 750)
        self.assertTrue(20 <= active[1] < active[3] <= 75)

        warning = ultimate._recognize_flee_warning(self._flee_warning_frame())
        self.assertIsNotNone(warning)
        fight, flee = warning
        self.assertTrue(100 <= fight[0] < fight[2] <= 331)
        self.assertTrue(470 <= flee[0] < flee[2] <= 701)

    def test_real_production_recognizers_reject_wrong_and_ambiguous_frames(self) -> None:
        main = self._main_frame()
        active = self._active_battle_frame()
        self.assertIsNone(ultimate._recognize_ultimate_main(active))
        self.assertIsNone(ultimate._recognize_active_battle(main))
        self.assertIsNone(ultimate._recognize_flee_warning(main))
        self.assertIsNone(ultimate._recognize_ultimate_main(self._main_frame("Resource Shop")))
        self.assertIsNone(
            ultimate._recognize_flee_warning(
                self._flee_warning_frame(text="Flee now: success")
            )
        )

        ambiguous_main = self._main_frame()
        cv2.rectangle(ambiguous_main, (280, 1170), (520, 1260), (24, 28, 36), -1)
        cv2.rectangle(ambiguous_main, (205, 1170), (385, 1260), (0, 0, 220), -1)
        cv2.rectangle(ambiguous_main, (415, 1170), (595, 1260), (0, 0, 220), -1)
        self.assertIsNone(ultimate._recognize_ultimate_main(ambiguous_main))

        ambiguous_warning = self._flee_warning_frame(extra_panel=True)
        self.assertIsNone(ultimate._recognize_flee_warning(ambiguous_warning))

    def test_home_template_rejects_deterministic_shop_like_frame(self) -> None:
        result = recognize_home_nav(self._shop_like_frame())
        self.assertFalse(result.is_home)
        self.assertIsNone(result.quest_tap_point())

    def test_ambiguous_visual_controls_fail_closed(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.rectangle(frame, (230, 1180), (410, 1250), (0, 0, 255), -1)
        cv2.rectangle(frame, (430, 1180), (610, 1250), (0, 0, 255), -1)
        self.assertIsNone(ultimate._bind_red_challenge_button(frame))

        with patch.object(
            ultimate,
            "_campaign_context_recognized",
            return_value=True,
        ), patch.object(
            ultimate,
            "_blue_vortex_candidates",
            return_value=[(480, 780, 620, 920), (500, 780, 640, 920)],
        ):
            observation = ultimate._bind_ultimate_challenge_entry(
                np.zeros((1280, 800, 3), dtype=np.uint8),
                reset_identity="game-day-2026-08-17",
            )
        self.assertFalse(observation.entry_control_visible)
        self.assertIsNone(observation.entry_roi)

    def test_home_check_is_template_only_not_generic_text(self) -> None:
        source = Path(ultimate.__file__).read_text(encoding="utf-8")
        self.assertIn("recognize_home_nav", source)
        self.assertNotIn("_ocr_folded", source)
        self.assertNotIn("_UC_RETAINED_SOURCE", source)

    def test_unexpected_overlay_rejects_each_actionable_state(self) -> None:
        blank = np.zeros((1280, 800, 3), dtype=np.uint8)
        with patch.object(ultimate, "_unexpected_visual_popup", return_value=True):
            self.assertIsNone(ultimate._recognize_ultimate_main(blank))
            self.assertIsNone(ultimate._bind_lineup_challenge_button(blank))
            self.assertIsNone(ultimate._recognize_active_battle(blank))
            observation = ultimate._bind_ultimate_challenge_entry(
                blank,
                reset_identity="game-day-2026-08-17",
            )
        self.assertFalse(observation.entry_control_visible)

    def test_popup_detector_uses_shared_visual_panel_primitive(self) -> None:
        blank = np.zeros((1280, 800, 3), dtype=np.uint8)
        with patch.object(
            ultimate,
            "_visual_popup_panel_candidates",
            return_value=[(50, 400, 750, 800)],
        ):
            self.assertTrue(ultimate._unexpected_visual_popup(blank))
            self.assertIsNone(ultimate._recognize_ultimate_main(blank))
            self.assertIsNone(ultimate._bind_active_battle_exit(blank))

    def test_flee_warning_requires_one_bounded_spatially_matched_popup(self) -> None:
        """R7 acceptance: an extra full-frame popup must fail closed."""
        valid_frame = self._flee_warning_frame()
        self.assertIsNotNone(ultimate._recognize_flee_warning(valid_frame))

        overbroad_frame = valid_frame.copy()
        # Independently measured full-frame panel, deliberately separate from
        # the modal geometry above and from production ROI constants.
        cv2.rectangle(
            overbroad_frame,
            (8, 18),
            (792, 1262),
            (180, 180, 180),
            12,
        )
        self.assertEqual(overbroad_frame.shape, (1280, 800, 3))
        self.assertIsNone(ultimate._recognize_flee_warning(overbroad_frame))

    def test_flee_popup_collapses_duplicate_modal_detections(self) -> None:
        """Candidate-clustering unit coverage, separate from r7 acceptance."""
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        duplicate = (67, 367, 733, 743)
        with patch.object(
            ultimate,
            "_visual_popup_candidates",
            return_value=[ultimate._FLEE_MODAL_ROI, duplicate],
        ):
            panels = ultimate._flee_popup_panel_candidates(frame)
        self.assertEqual(len(panels), 1)
        self.assertTrue(ultimate._flee_modal_popup_matches(panels[0]))

    def test_repair_rebinds_entry_on_exact_immediate_before_and_enforces_ceiling(self) -> None:
        source = Path(ultimate.__file__).read_text(encoding="utf-8")
        self.assertIn('runtime.capture("uc-entry-immediate-before")', source)
        self.assertIn("fresh_entry = _bind_ultimate_challenge_entry", source)
        self.assertEqual(ultimate.MAX_TOTAL_INPUTS, 16)
        self.assertIn("--max-total-inputs", source)


class UltimateChallengeOperatorTests(unittest.TestCase):
    class FakePnsctl:
        BLUESTACKS_ADB = Path("fake-adb")
        BLUESTACKS_SERIAL = "emulator-5554"
        BLUESTACKS_NATIVE_WIDTH = 800
        BLUESTACKS_NATIVE_HEIGHT = 1280
        OperatorError = RuntimeError

        def __init__(self, root: Path) -> None:
            self.BLUESTACKS_ARTIFACT_ROOT = root

    def test_result_writer_centralizes_terminal_artifacts_and_preserves_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            existing = {"flow_id": FLOW_ID, "event": "substantive-existing-row"}
            (session / "frames").mkdir()
            (session / "frames" / "source.png").write_bytes(b"native-source")
            (session / "events.jsonl").write_text(
                json.dumps(
                    {
                        "flow_id": FLOW_ID,
                        "type": "substantive-source-event",
                        "source_frame_sha256": "a" * 64,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            for name in ("ledger.jsonl", "capability-audit.jsonl", "journal.jsonl"):
                (session / name).write_text(
                    json.dumps(existing) + "\n",
                    encoding="utf-8",
                )

            with patch("builtins.print"):
                ultimate._write_result(
                    session,
                    {
                        "flow_id": FLOW_ID,
                        "status": "blocked_fail_closed",
                        "terminal": "blocked_fail_closed",
                        "reason": "LOCALIZATION_NOT_RECOGNIZED",
                        "input_count": 0,
                    },
                )
                ultimate._write_result(
                    session,
                    {
                        "flow_id": FLOW_ID,
                        "status": "blocked_fail_closed",
                        "terminal": "blocked_fail_closed",
                        "reason": "LOCALIZATION_NOT_RECOGNIZED",
                        "input_count": 0,
                    },
                )

            result = json.loads((session / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["terminal"], "blocked_fail_closed")
            for name in ("ledger.jsonl", "capability-audit.jsonl", "journal.jsonl"):
                rows = [
                    json.loads(line)
                    for line in (session / name).read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                self.assertEqual(rows[0], existing)
                self.assertEqual(rows[-1]["terminal"], result["terminal"])
                self.assertEqual(
                    sum(row.get("record_type") == "operator_terminal" for row in rows),
                    1,
                )

    def test_reset_precheck_blocked_terminal_retains_current_evidence(self) -> None:
        captured_frames: list[CapturedNativeFrame] = []

        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [type("Device", (), {"serial": "emulator-5554", "state": "device"})()]

            def get_state(self) -> str:
                return "device"

        class FakeRuntime:
            input_count = 0

            def __init__(self, runner, session: Path, *, execute: bool) -> None:
                self.runner = runner
                self.session = session
                self.execute = execute
                self.frame_directory = session / "frames"
                self.frame_directory.mkdir(parents=True, exist_ok=True)

            def capture(self, label: str) -> CapturedNativeFrame:
                frame = np.zeros((1280, 800, 3), dtype=np.uint8)
                encoded_ok, encoded = cv2.imencode(".png", frame)
                assert encoded_ok
                payload = encoded.tobytes()
                path = self.frame_directory / f"{len(captured_frames) + 1:04d}-{label}.png"
                path.write_bytes(payload)
                captured = CapturedNativeFrame(
                    frame=frame,
                    png=payload,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    captured_monotonic=0.0,
                    path=path,
                )
                captured_frames.append(captured)
                return captured

        blocked_reason = "completion_state=completed but last success is outside current reset window"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(ultimate, "ADBRunner", FakeRunner), patch.object(
                ultimate, "LocalBlueStacksRuntime", FakeRuntime
            ), patch.object(
                ultimate, "is_permitted_local_bluestacks_serial", return_value=True
            ), patch.object(
                ultimate, "require_campaign_home_atlas_building"
            ), patch.object(
                ultimate,
                "evaluate_already_completed",
                return_value=SimpleNamespace(
                    terminal="blocked_fail_closed",
                    reason=blocked_reason,
                ),
            ):
                code = ultimate.main(
                    [
                        "--adb",
                        "unused-adb",
                        "--serial",
                        "emulator-5554",
                        "--daily",
                        "--execute",
                        "--yes",
                        "--output-directory",
                        str(output),
                        "--reset-identity",
                        "game-day-2026-08-17",
                    ]
                )

            sessions = list(output.glob("blocked-*"))
            self.assertEqual(code, 3)
            self.assertEqual(len(sessions), 1)
            session = sessions[0]
            retained, frame_paths = require_operator_evidence(session)
            self.assertEqual(retained["reason"], blocked_reason)
            self.assertEqual(retained["input_count"], 0)
            self.assertEqual(frame_paths, ["frames/reset-precheck-blocked-source.png"])
            events = [
                json.loads(line)
                for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(event["type"] == "reset_precheck_blocked" for event in events))
            self.assertEqual(len(captured_frames), 1)

    def test_post_flee_home_immediate_failure_retains_current_evidence(self) -> None:
        captured_frames: list[CapturedNativeFrame] = []

        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [type("Device", (), {"serial": "emulator-5554", "state": "device"})()]

            def get_state(self) -> str:
                return "device"

        class FakeRuntime:
            input_count = 0

            def __init__(self, runner, session: Path, *, execute: bool) -> None:
                self.runner = runner
                self.session = session
                self.execute = execute
                self.frame_directory = session / "frames"
                self.frame_directory.mkdir(parents=True, exist_ok=True)

            def capture(self, label: str) -> CapturedNativeFrame:
                frame = np.zeros((1280, 800, 3), dtype=np.uint8)
                encoded_ok, encoded = cv2.imencode(".png", frame)
                assert encoded_ok
                payload = encoded.tobytes()
                path = self.frame_directory / f"{len(captured_frames) + 1:04d}-{label}.png"
                path.write_bytes(payload)
                captured = CapturedNativeFrame(
                    frame=frame,
                    png=payload,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    captured_monotonic=0.0,
                    path=path,
                )
                captured_frames.append(captured)
                return captured

        blocked_reason = "post-Flee Ultimate Challenge main not positively recognized"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(ultimate, "ADBRunner", FakeRunner), patch.object(
                ultimate, "LocalBlueStacksRuntime", FakeRuntime
            ), patch.object(
                ultimate, "is_permitted_local_bluestacks_serial", return_value=True
            ), patch.object(
                ultimate, "require_campaign_home_atlas_building"
            ), patch.object(
                ultimate, "_recognize_ultimate_main", return_value=None
            ):
                code = ultimate.main(
                    [
                        "--adb",
                        "unused-adb",
                        "--serial",
                        "emulator-5554",
                        "--post-flee-home-only",
                        "--execute",
                        "--yes",
                        "--output-directory",
                        str(output),
                        "--reset-identity",
                        "game-day-2026-08-17",
                    ]
                )

            sessions = list(output.glob("nav-*"))
            self.assertEqual(code, 3)
            self.assertEqual(len(sessions), 1)
            session = sessions[0]
            retained, frame_paths = require_operator_evidence(session)
            self.assertEqual(retained["reason"], blocked_reason)
            self.assertEqual(retained["input_count"], 0)
            self.assertEqual(
                frame_paths,
                ["frames/post-flee-ultimate-immediate-before.png"],
            )
            events = [
                json.loads(line)
                for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(event["type"] == "post_flee_home_source" for event in events))
            self.assertEqual(len(captured_frames), 1)

    def test_localization_blocked_early_return_retains_zero_input_evidence(self) -> None:
        captured_frames: list[CapturedNativeFrame] = []

        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [type("Device", (), {"serial": "emulator-5554", "state": "device"})()]

            def get_state(self) -> str:
                return "device"

        class FakeRuntime:
            input_count = 0

            def __init__(self, _runner, session: Path, *, execute: bool) -> None:
                self.session = session
                self.execute = execute
                self.frame_directory = session / "frames"
                self.frame_directory.mkdir(parents=True, exist_ok=True)

            def capture(self, label: str) -> CapturedNativeFrame:
                frame = np.zeros((1280, 800, 3), dtype=np.uint8)
                encoded_ok, encoded = cv2.imencode(".png", frame)
                assert encoded_ok
                payload = encoded.tobytes()
                path = self.frame_directory / f"{len(captured_frames) + 1:04d}-{label}.png"
                path.write_bytes(payload)
                captured = CapturedNativeFrame(
                    frame=frame,
                    png=payload,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    captured_monotonic=0.0,
                    path=path,
                )
                captured_frames.append(captured)
                return captured

        def fake_entry(frame, *, reset_identity):
            self.assertIsInstance(frame, np.ndarray)
            return UltimateChallengeEntryObservation(
                campaign_screen_recognized=False,
                entry_control_visible=False,
                entry_control_identity="",
                entry_roi=None,
                already_completed_marker=False,
                reset_identity=reset_identity,
                source_frame_sha256=ultimate.frame_sha256(frame),
            )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(ultimate, "ADBRunner", FakeRunner), patch.object(
                ultimate, "LocalBlueStacksRuntime", FakeRuntime
            ), patch.object(
                ultimate, "is_permitted_local_bluestacks_serial", return_value=True
            ), patch.object(
                ultimate, "require_campaign_home_atlas_building"
            ), patch.object(
                ultimate, "_recognize_ultimate_main", return_value=None
            ), patch.object(
                ultimate, "_bind_lineup_challenge_button", return_value=None
            ), patch.object(
                ultimate, "_recognize_active_battle", return_value=None
            ), patch.object(
                ultimate, "_bind_flee_warning_button", return_value=None
            ), patch.object(
                ultimate, "_bind_ultimate_challenge_entry", side_effect=fake_entry
            ), patch.object(
                ultimate, "_home_nav_terminal", return_value=True
            ), patch.object(
                ultimate,
                "run_verified_ultimate_challenge_campaign_door",
                return_value={
                    "status": "blocked_fail_closed",
                    "reason": "LOCALIZATION_NOT_RECOGNIZED",
                    "records": [],
                },
            ):
                code = ultimate.main(
                    [
                        "--adb",
                        "unused-adb",
                        "--serial",
                        "emulator-5554",
                        "--daily",
                        "--execute",
                        "--yes",
                        "--output-directory",
                        str(output),
                        "--reset-identity",
                        "game-day-2026-08-17",
                    ]
                )

            sessions = list(output.glob("nav-*"))
            self.assertEqual(code, 3)
            self.assertEqual(len(sessions), 1)
            session = sessions[0]
            result = json.loads((session / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["terminal"], "blocked_fail_closed")
            self.assertEqual(result["reason"], "LOCALIZATION_NOT_RECOGNIZED")
            self.assertEqual(result["input_count"], 0)
            for name in ("ledger.jsonl", "capability-audit.jsonl", "journal.jsonl"):
                self.assertGreater((session / name).stat().st_size, 0)
            retained, frames = require_operator_evidence(session)
            self.assertEqual(retained, result)
            self.assertEqual(
                json.loads(
                    (session / "journal.jsonl").read_text(encoding="utf-8").splitlines()[-1]
                )["terminal"],
                result["terminal"],
            )
            self.assertTrue(frames)

    def test_main_unwraps_captured_frames_for_resume_and_navigation_binding(self) -> None:
        captured_frames: list[CapturedNativeFrame] = []
        runtime_instances = []

        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [type("Device", (), {"serial": "emulator-5554", "state": "device"})()]

            def get_state(self) -> str:
                return "device"

        class FakeRuntime:
            input_count = 0

            def __init__(self, _runner, session: Path, *, execute: bool) -> None:
                self.session = session
                self.execute = execute
                self.frame_directory = session / "frames"
                self.frame_directory.mkdir(parents=True, exist_ok=True)

            def capture(self, label: str) -> CapturedNativeFrame:
                frame = np.zeros((1280, 800, 3), dtype=np.uint8)
                encoded_ok, encoded = cv2.imencode(".png", frame)
                assert encoded_ok
                payload = encoded.tobytes()
                path = self.frame_directory / f"{len(captured_frames) + 1:04d}-{label}.png"
                path.write_bytes(payload)
                captured = CapturedNativeFrame(
                    frame=frame,
                    png=payload,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    captured_monotonic=0.0,
                    path=path,
                )
                captured_frames.append(captured)
                return captured

        def fake_runtime(*args, **kwargs):
            runtime = FakeRuntime(*args, **kwargs)
            runtime_instances.append(runtime)
            return runtime

        def recognize_main(frame):
            self.assertIsInstance(frame, np.ndarray)
            cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            return (320, 1195, 480, 1245)

        def recognize_other(frame):
            self.assertIsInstance(frame, np.ndarray)
            cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            return None

        def bind_entry(frame, *, reset_identity):
            self.assertIsInstance(frame, np.ndarray)
            cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            return UltimateChallengeEntryObservation(
                campaign_screen_recognized=True,
                entry_control_visible=True,
                entry_control_identity=ULTIMATE_CHALLENGE_ENTRY_IDENTITY,
                entry_roi=(480, 780, 620, 920),
                already_completed_marker=False,
                reset_identity=reset_identity,
                source_frame_sha256=ultimate.frame_sha256(frame),
            )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(ultimate, "ADBRunner", FakeRunner), patch.object(
                ultimate, "LocalBlueStacksRuntime", side_effect=fake_runtime
            ), patch.object(
                ultimate, "is_permitted_local_bluestacks_serial", return_value=True
            ), patch.object(
                ultimate, "require_campaign_home_atlas_building"
            ), patch.object(
                ultimate, "_recognize_ultimate_main", side_effect=recognize_main
            ), patch.object(
                ultimate, "_bind_lineup_challenge_button", side_effect=recognize_other
            ), patch.object(
                ultimate, "_recognize_active_battle", side_effect=recognize_other
            ), patch.object(
                ultimate, "_bind_flee_warning_button", side_effect=recognize_other
            ), patch.object(
                ultimate, "_bind_ultimate_challenge_entry", side_effect=bind_entry
            ):
                result = ultimate.main(
                    [
                        "--adb",
                        "unused-adb",
                        "--serial",
                        "emulator-5554",
                        "--navigation-only",
                        "--execute",
                        "--yes",
                        "--output-directory",
                        str(output),
                        "--reset-identity",
                        "game-day-2026-08-17",
                    ]
                )
                session_directories = list(output.glob("nav-*"))
                evidence_paths = [
                    session_directories[0] / "frames" / "campaign-resume-source.png",
                    session_directories[0] / "frames" / "uc-entry-bind.png",
                ] if len(session_directories) == 1 else []
                self.assertEqual(len(session_directories), 1)
                self.assertTrue(all(path.is_file() for path in evidence_paths))

        self.assertEqual(result, 0)
        self.assertEqual(len(runtime_instances), 1)
        self.assertGreaterEqual(len(captured_frames), 2)
        self.assertTrue(all(isinstance(frame, CapturedNativeFrame) for frame in captured_frames))

    def test_capture_until_passes_numpy_frame_but_returns_capture_object(self) -> None:
        class Runtime:
            def __init__(self, captured: CapturedNativeFrame) -> None:
                self.captured = captured

            def capture(self, _label: str) -> CapturedNativeFrame:
                return self.captured

        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        captured = CapturedNativeFrame(
            frame=frame,
            png=b"png",
            sha256="a" * 64,
            captured_monotonic=0.0,
            path=Path("capture.png"),
        )
        seen: list[np.ndarray] = []

        def predicate(candidate: np.ndarray) -> bool:
            seen.append(candidate)
            cv2.cvtColor(candidate, cv2.COLOR_BGR2HSV)
            return True

        result = ultimate._capture_until(
            Runtime(captured),
            label="strict-capture-boundary",
            predicate=predicate,
            attempts=1,
            settle_seconds=0,
        )

        self.assertIs(result, captured)
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0], frame)

    def _run_wrapper(
        self,
        root: Path,
        *,
        terminal: str,
        home_nav_recognized: bool,
        child_returncode: int | None = None,
        input_count: int = 0,
        expect_failure: bool | None = None,
        queue_diagnosis: str = "historical gold Flee input diagnosis",
        queue_context: dict | None = None,
        lease_context: dict | None = None,
    ):
        fake_pnsctl = self.FakePnsctl(root / "artifacts")
        commands: list[list[str]] = []
        result = {
            "flow_id": FLOW_ID,
            "terminal": terminal,
            "status": terminal,
            "home_nav_recognized": home_nav_recognized,
            "input_count": input_count,
            "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0},
        }

        def fake_run(command, **_kwargs):
            commands.append(command)
            output = Path(command[command.index("--output-directory") + 1])
            child = output / "nav-child"
            frames = child / "frames"
            frames.mkdir(parents=True, exist_ok=True)
            frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            if home_nav_recognized:
                template_path = (
                    ROOT
                    / "tasks/assets/home_nav/800x1280/home_nav_strip.png"
                )
                template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
                frame[1213:1280, 0:800] = template
            frame_path = frames / "canonical-home-terminal.png"
            cv2.imwrite(str(frame_path), frame)
            payload = frame_path.read_bytes()
            result["home_frame"] = "frames/canonical-home-terminal.png"
            result["home_frame_sha256"] = hashlib.sha256(payload).hexdigest()
            return __import__("subprocess").CompletedProcess(
                command,
                child_returncode
                if child_returncode is not None
                else (0 if terminal != "blocked_fail_closed" else 3),
                "",
                "",
            )

        queue = queue_context or {
            "flows": [
                {
                    "flow_id": FLOW_ID,
                    "maximum_live_attempts": 4,
                    "live_attempts": [{"diagnosis": queue_diagnosis}],
                }
            ]
        }
        lease = lease_context or {"owner": "test-owner"}
        state_path = root / ".local-captures" / "reset-window.json"
        with patch.object(delivery, "_pnsctl", return_value=fake_pnsctl), patch.object(
            delivery, "_reset_window_state_path", return_value=state_path
        ), patch.object(delivery.subprocess, "run", side_effect=fake_run), patch.object(
            delivery, "require_operator_evidence", return_value=(result, ["runtime/frames/source.png"])
        ), patch.object(
            delivery, "load_reset_window_state", return_value=empty_reset_window_state()
        ) as load_state, patch.object(
            delivery, "record_verified_home_success", return_value=empty_reset_window_state()
        ) as record_home, patch.object(
            delivery, "save_reset_window_state"
        ) as save_state:
            if expect_failure is None:
                expect_failure = terminal == "blocked_fail_closed" or (
                    terminal == "complete_for_reset" and not home_nav_recognized
                ) or (
                    terminal == "already_completed" and not home_nav_recognized
                )
            if expect_failure:
                with self.assertRaises(RuntimeError):
                    delivery.run_ultimate_challenge_daily(queue, lease)
            else:
                delivery.run_ultimate_challenge_daily(queue, lease)
        return commands[0], load_state, record_home, save_state

    def test_daily_wrapper_accepts_minimal_development_session_context(self) -> None:
        queue = {"active_flow_id": FLOW_ID, "development_session": True}
        lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
            "development_session": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command, _load_state, _record_home, _save_state = self._run_wrapper(
                root,
                terminal="already_completed",
                home_nav_recognized=True,
                queue_context=queue,
                lease_context=lease,
            )
            result_paths = list(
                (root / "artifacts" / FLOW_ID).glob(
                    "daily-*/nav-child/flow-delivery-result.json"
                )
            )
            self.assertEqual(len(result_paths), 1)
            delivery_result = json.loads(result_paths[0].read_text(encoding="utf-8"))

        self.assertEqual(command[command.index("--max-total-inputs") + 1], "16")
        self.assertIsNone(delivery_result["attempt_budget"])
        self.assertIsNone(delivery_result["legacy_attempt_budget"])
        self.assertEqual(delivery_result["max_inputs"], 16)
        self.assertEqual(delivery_result["session_max_inputs"], 16)

    def test_daily_wrapper_rejects_invalid_development_session_context_before_child(
        self,
    ) -> None:
        valid_queue = {"active_flow_id": FLOW_ID, "development_session": True}
        valid_lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
            "development_session": True,
        }
        invalid_contexts = []
        for label, queue, lease in (
            (
                "wrong flow",
                {**valid_queue, "active_flow_id": "OTHER-FLOW"},
                valid_lease,
            ),
            ("missing flow", {"development_session": True}, valid_lease),
            (
                "released runtime",
                valid_queue,
                {**valid_lease, "runtime_ownership_state": "released"},
            ),
            (
                "missing ceiling",
                valid_queue,
                {key: value for key, value in valid_lease.items() if key != "max_inputs"},
            ),
            ("invalid ceiling", valid_queue, {**valid_lease, "max_inputs": "16"}),
            ("over ceiling", valid_queue, {**valid_lease, "max_inputs": 17}),
        ):
            invalid_contexts.append((label, queue, lease))

        for label, queue, lease in invalid_contexts:
            with self.subTest(context=label), tempfile.TemporaryDirectory() as directory:
                fake_pnsctl = self.FakePnsctl(Path(directory) / "artifacts")
                with patch.object(
                    delivery, "_pnsctl", return_value=fake_pnsctl
                ), patch.object(delivery.subprocess, "run") as child:
                    with self.assertRaisesRegex(RuntimeError, "Ultimate Challenge"):
                        delivery.run_ultimate_challenge_daily(queue, lease)
                child.assert_not_called()

    def test_daily_wrapper_uses_current_reset_and_ignores_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            command, load_state, record_home, save_state = self._run_wrapper(
                Path(directory),
                terminal="complete_for_reset",
                home_nav_recognized=True,
            )
        self.assertIn("--daily", command)
        self.assertNotIn("--post-flee-home-only", command)
        identity = command[command.index("--reset-identity") + 1]
        self.assertEqual(
            identity,
            f"game-day-{datetime.now(timezone.utc).date().isoformat()}",
        )
        state_path = Path(command[command.index("--reset-state-path") + 1])
        self.assertIn(".local-captures", state_path.parts)
        self.assertTrue(state_path.name.endswith(".json"))
        load_state.assert_called_once_with(state_path)
        record_home.assert_called_once()
        save_state.assert_called_once()

    def test_persistence_requires_verified_home_terminal(self) -> None:
        for terminal in ("blocked_fail_closed", "complete_for_reset"):
            with self.subTest(terminal=terminal):
                with tempfile.TemporaryDirectory() as directory:
                    _command, load_state, record_home, save_state = self._run_wrapper(
                        Path(directory),
                        terminal=terminal,
                        home_nav_recognized=False,
                    )
                load_state.assert_not_called()
                record_home.assert_not_called()
                save_state.assert_not_called()

    def test_complete_for_reset_nonzero_child_exit_does_not_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _command, load_state, record_home, save_state = self._run_wrapper(
                Path(directory),
                terminal="complete_for_reset",
                home_nav_recognized=True,
                child_returncode=3,
                expect_failure=True,
            )
        load_state.assert_not_called()
        record_home.assert_not_called()
        save_state.assert_not_called()

    def test_complete_for_reset_over_budget_does_not_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _command, load_state, record_home, save_state = self._run_wrapper(
                Path(directory),
                terminal="complete_for_reset",
                home_nav_recognized=True,
                input_count=delivery.MAX_TOTAL_INPUTS + 1,
                expect_failure=True,
            )
        load_state.assert_not_called()
        record_home.assert_not_called()
        save_state.assert_not_called()

    def test_already_completed_is_idempotent_without_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _command, load_state, record_home, save_state = self._run_wrapper(
                Path(directory),
                terminal="already_completed",
                home_nav_recognized=False,
            )
        load_state.assert_not_called()
        record_home.assert_not_called()
        save_state.assert_not_called()

    def test_already_completed_home_is_verified_without_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _command, load_state, record_home, save_state = self._run_wrapper(
                Path(directory),
                terminal="already_completed",
                home_nav_recognized=True,
            )
        load_state.assert_not_called()
        record_home.assert_not_called()
        save_state.assert_not_called()

    def test_wrapper_home_evidence_rejects_tamper_and_non_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            template = cv2.imread(
                str(ROOT / "tasks/assets/home_nav/800x1280/home_nav_strip.png"),
                cv2.IMREAD_COLOR,
            )
            home = np.zeros((1280, 800, 3), dtype=np.uint8)
            home[1213:1280] = template
            path = frames / "canonical-home-terminal.png"
            cv2.imwrite(str(path), home)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result = {
                "home_nav_recognized": True,
                "home_frame": "frames/canonical-home-terminal.png",
                "home_frame_sha256": digest,
            }
            self.assertTrue(delivery._verified_home_evidence(root, result)[0])
            path.write_bytes(b"tampered")
            self.assertFalse(delivery._verified_home_evidence(root, result)[0])

    def test_verifier_rejects_tampered_home_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            path = frames / "canonical-home-terminal.png"
            cv2.imwrite(str(path), frame)
            result = {
                "flow_id": FLOW_ID,
                "terminal_runtime_state": "recognized_home",
                "input_count": 0,
                "ultimate_challenge_result": {
                    "terminal": "complete_for_reset",
                    "home_nav_recognized": True,
                    "input_count": 0,
                    "home_frame": "frames/canonical-home-terminal.png",
                    "home_frame_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                },
            }
            path.write_bytes(b"tampered")
            fake = self.FakePnsctl(root)
            with patch.object(delivery, "_pnsctl", return_value=fake):
                with self.assertRaises(RuntimeError):
                    delivery.verify_ultimate_challenge_daily(
                        {"result": result, "session_directory": str(root)},
                        {"flows": [{"flow_id": FLOW_ID, "maximum_live_attempts": 4, "live_attempt_count": 0}]},
                        {},
                    )

    def test_navigation_verifier_distinguishes_entry_from_home(self) -> None:
        fake = self.FakePnsctl(Path("."))
        queue = {
            "flows": [
                {
                    "flow_id": FLOW_ID,
                    "required_terminal_states": ["already_completed"],
                }
            ]
        }
        structure = {
            "session_directory": ".",
            "actions": [],
            "result": {
                "flow_id": FLOW_ID,
                "terminal_runtime_state": "ultimate_challenge_entry_recognized",
                "ultimate_challenge_result": {
                    "terminal": "navigation_only_complete",
                    "terminal_runtime_state": "ultimate_challenge_entry_recognized",
                },
            },
        }
        with patch.object(delivery, "_pnsctl", return_value=fake):
            verified = delivery.verify_ultimate_challenge_navigation_only(
                structure, queue, {}
            )
        self.assertEqual(verified["terminal"], "navigation_only_complete")

        structure["result"]["terminal_runtime_state"] = "recognized_home"
        with patch.object(delivery, "_pnsctl", return_value=fake):
            with self.assertRaises(RuntimeError):
                delivery.verify_ultimate_challenge_navigation_only(
                    structure, queue, {}
                )


if __name__ == "__main__":
    unittest.main()
