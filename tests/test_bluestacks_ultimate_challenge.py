"""Offline visual and operator-contract checks for Ultimate Challenge Daily."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import bluestacks_ultimate_challenge as ultimate
from scripts import flow_delivery_ultimate_challenge_bluestacks as delivery
from tasks.home_nav_recognition import recognize_home_nav
from tasks.ultimate_challenge_daily import FLOW_ID, empty_reset_window_state


ROOT = Path(__file__).resolve().parents[1]
RETAINED = {
    "ultimate_main": ROOT
    / ".local-captures/flow-delivery/ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION/"
    "daily-20260726T233710531717Z/nav-20260726T233711004690Z/runtime/frames/"
    "0001-post-flee-ultimate-immediate-before.png",
    "active_battle": ROOT
    / ".local-captures/flow-delivery/ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION/"
    "daily-20260726T232707275062Z/nav-20260726T232707732974Z/runtime/frames/"
    "0001-active-battle-resume-source.png",
    "flee_warning": ROOT
    / ".local-captures/flow-delivery/ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION/"
    "daily-20260726T233344160030Z/nav-20260726T233344610221Z/runtime/frames/"
    "0001-flee-warning-resume-source.png",
    "flee_successor": ROOT
    / ".local-captures/flow-delivery/ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION/"
    "daily-20260726T233344160030Z/nav-20260726T233344610221Z/runtime/frames/"
    "0002-flee-confirmed-successor-01.png",
    "resource_shop": ROOT
    / ".local-captures/flow-delivery/ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION/"
    "daily-20260726T233710531717Z/nav-20260726T233711004690Z/runtime/frames/"
    "0003-canonical-home-successor-01.png",
}


class UltimateChallengeVisualTests(unittest.TestCase):
    def _load_available(self, name: str) -> np.ndarray:
        path = RETAINED[name]
        if not path.is_file():
            self.skipTest(f"retained frame absent for {name}")
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame, f"could not read retained frame {path}")
        return frame

    def test_retained_frames_bind_only_their_correct_state_targets(self) -> None:
        available = [name for name, path in RETAINED.items() if path.is_file()]
        if not available:
            self.skipTest("no retained Ultimate Challenge frames present")

        for name in available:
            with self.subTest(screen=name):
                frame = self._load_available(name)
                main = ultimate._recognize_ultimate_main(frame)
                active = ultimate._recognize_active_battle(frame)
                warning = ultimate._recognize_flee_warning(frame)
                if name in {"ultimate_main", "flee_successor"}:
                    self.assertIsNotNone(main)
                    self.assertIsNone(active)
                    self.assertIsNone(warning)
                elif name == "active_battle":
                    self.assertIsNone(main)
                    self.assertIsNotNone(active)
                    self.assertIsNone(warning)
                elif name == "flee_warning":
                    self.assertIsNone(main)
                    self.assertIsNone(active)
                    self.assertIsNotNone(warning)
                    self.assertIsNotNone(ultimate._bind_flee_warning_button(frame))
                else:
                    self.assertIsNone(main)
                    self.assertIsNone(active)
                    self.assertIsNone(warning)

    def test_resource_shop_is_rejected_as_home(self) -> None:
        frame = self._load_available("resource_shop")
        result = recognize_home_nav(frame)
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
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)

        def controls(_frame, *, search_roi, **_kwargs):
            if search_roi == ultimate._FLEE_FIGHT_SEARCH_ROI:
                return [(100, 600, 300, 700)]
            if search_roi == ultimate._FLEE_FLEE_SEARCH_ROI:
                return [(450, 600, 700, 700)]
            raise AssertionError(f"unexpected control search ROI: {search_roi}")

        def recognize_with(panels):
            with patch.object(
                ultimate,
                "_visual_popup_candidates",
                return_value=panels,
            ), patch.object(
                ultimate,
                "_has_warning_modal_geometry",
                return_value=True,
            ), patch.object(
                ultimate,
                "_visual_control_candidates",
                side_effect=controls,
            ), patch.object(
                ultimate,
                "_ocr_region_text",
                return_value="flee now failure",
            ):
                return ultimate._recognize_flee_warning(frame)

        self.assertIsNotNone(recognize_with([(80, 380, 720, 730)]))
        for panels in (
            [
                ultimate._FLEE_MODAL_ROI,
                (0, 0, 200, 200),
            ],
            [
                ultimate._FLEE_MODAL_ROI,
                (0, 0, 800, 1280),
            ],
            [(0, 0, 200, 200)],
            [(65, 365, 400, 745)],
            [(0, 0, 200, 500)],
            [(0, 0, 800, 1280)],
        ):
            with self.subTest(panels=panels):
                self.assertIsNone(recognize_with(panels))

    def test_overbroad_popup_remains_visible_beside_expected_modal(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        panels = [ultimate._FLEE_MODAL_ROI, (0, 0, 800, 1280)]
        with patch.object(
            ultimate,
            "_visual_popup_candidates",
            return_value=panels,
        ):
            self.assertEqual(ultimate._flee_popup_panel_candidates(frame), panels)

    def test_flee_popup_collapses_duplicate_modal_detections(self) -> None:
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
