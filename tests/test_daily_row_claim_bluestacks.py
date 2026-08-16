from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import daily_row_claim_bluestacks as daily
from scripts import flow_delivery_control as control
from scripts import navigation_development_boundary as boundary
from scripts import pnsctl
from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime


def _frame(
    root: Path,
    label: str,
    *,
    age: float = 0.0,
    image: np.ndarray | None = None,
) -> CapturedNativeFrame:
    image = image if image is not None else np.zeros((1280, 800, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    payload = encoded.tobytes()
    path = root / f"{label}.png"
    path.write_bytes(payload)
    return CapturedNativeFrame(
        image,
        payload,
        hashlib.sha256(payload).hexdigest(),
        time.monotonic() - age,
        path,
    )


class FakeRuntime:
    execute = True
    frame_max_age_seconds = 30.0

    def __init__(self, root: Path, *, stale: bool = False) -> None:
        self.session = root / "runtime"
        self.session.mkdir(parents=True)
        self.events = self.session / "events.jsonl"
        self._root = root
        self._stale = stale
        self.labels: list[str] = []
        self.taps: list[dict[str, object]] = []
        self.input_count = 0

    def capture(self, label: str) -> CapturedNativeFrame:
        self.labels.append(label)
        captured = _frame(self.session, label, age=60.0 if self._stale else 0.0)
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "capture", "label": label}) + "\n")
        return captured

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: tuple[int, int, int, int],
        action_key: str,
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None:
        self.taps.append(
            {
                "target_identity": target_identity,
                "target_roi": target_roi,
                "action_key": action_key,
                "consequential": consequential,
                "continuation_of": continuation_of,
                "source_sha256": source.sha256,
            }
        )
        delegated = boundary.current_delegated_runtime_context()
        if delegated is not None:
            delegated.reserve_input(
                action_identity=target_identity,
                action_class="navigation",
                consequence_class="navigation_only",
                source_evidence_hash=source.sha256,
                action_key=action_key,
            )
            delegated.mark_transported(action_key)
        self.input_count += 1
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "dispatch",
                        "action_key": action_key,
                        "target_identity": target_identity,
                    }
                )
                + "\n"
            )


class VisualFakeRuntime(FakeRuntime):
    def capture(self, label: str) -> CapturedNativeFrame:
        self.labels.append(label)
        image = np.zeros((1280, 800, 3), dtype=np.uint8)
        if label in {"home-source", "home-quest-entry-immediate-before"}:
            cv2.rectangle(image, (30, 1000), (220, 1160), (0, 180, 255), -1)
        else:
            cv2.rectangle(image, (280, 20), (500, 190), (0, 180, 255), -1)
        captured = _frame(self.session, label, image=image)
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "capture", "label": label}) + "\n")
        return captured


class ModalOCR:
    """Keep narrow target OCR valid while adding a modal to selected full frames."""

    def __init__(self, modal_full_calls: set[int]) -> None:
        self.modal_full_calls = modal_full_calls
        self.full_calls = 0

    @staticmethod
    def _data(tokens: list[tuple[str, int, int, int, int]]) -> dict[str, list[object]]:
        return {
            "text": [item[0] for item in tokens],
            "left": [item[1] for item in tokens],
            "top": [item[2] for item in tokens],
            "width": [item[3] for item in tokens],
            "height": [item[4] for item in tokens],
            "conf": ["95"] * len(tokens),
        }

    def __call__(self, image: np.ndarray) -> dict[str, list[object]]:
        if image.shape[0] == 2560:
            tokens: list[tuple[str, int, int, int, int]] = []
            if self.full_calls in self.modal_full_calls:
                tokens.append(("confirm", 280, 500, 240, 80))
            self.full_calls += 1
            return self._data(tokens)
        if image.shape[0] == 560:
            return self._data(
                [
                    ("quest", 200, 100, 100, 40),
                    ("world", 400, 100, 100, 40),
                ]
            )
        return self._data(
            [
                ("quest", 100, 5, 100, 40),
                ("daily", 700, 70, 100, 40),
            ]
        )


class ScriptedRecognizer:
    def __init__(self, *, selected_daily: bool = True) -> None:
        self.selected_daily = selected_daily
        self.calls: list[tuple[str, str]] = []

    @staticmethod
    def _recognition(
        state: str,
        identity: str | None,
        roi: tuple[int, int, int, int] | None,
    ) -> daily.FrameRecognition:
        return daily.FrameRecognition(
            state,
            state != daily.UNKNOWN_STATE,
            identity if state != daily.UNKNOWN_STATE else None,
            roi if state != daily.UNKNOWN_STATE else None,
            state,
            {"independent_test_semantics": True},
        )

    def _label(self, frame: np.ndarray) -> str:
        # The fake runtime uses zero-valued frames; the recognizer call order
        # is intentionally separate from production geometry constants.
        return str(len(self.calls))

    def recognize_home(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.calls.append(("home", self._label(frame)))
        return self._recognition(
            daily.HOME_STATE,
            daily.HOME_QUEST_IDENTITY,
            (101, 1101, 207, 1187) if len(self.calls) == 1 else (127, 1118, 241, 1204),
        )

    def recognize_quest(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.calls.append(("quest", self._label(frame)))
        if not self.selected_daily:
            return self._recognition(daily.UNKNOWN_STATE, None, None)
        return self._recognition(
            daily.QUEST_STATE,
            daily.QUEST_DAILY_IDENTITY,
            (304, 74, 492, 146),
        )

    def recognize_daily_selected(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.calls.append(("daily", self._label(frame)))
        return self._recognition(
            daily.DAILY_SELECTED_STATE if self.selected_daily else daily.UNKNOWN_STATE,
            "daily-quest-selected" if self.selected_daily else None,
            (326, 78, 486, 152) if self.selected_daily else None,
        )


class DailyRowReconnaissanceTests(unittest.TestCase):
    def _session(self, root: Path) -> boundary.DevelopmentSession:
        return boundary.DevelopmentSession(
            owner="test-daily-row-recon",
            invocation_id="test-daily-row-recon",
            session_directory=root / "session",
            max_inputs=2,
        )

    def test_two_step_route_rebinds_current_geometry_and_retains_five_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = ScriptedRecognizer()
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=recognizer,
                )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["input_count"], 2)
        self.assertEqual(result["resource_affecting_inputs"], 0)
        self.assertEqual(result["combat_confirmations"], 0)
        self.assertEqual(
            runtime.labels,
            [
                "home-source",
                "home-quest-entry-immediate-before",
                "home-quest-entry-immediate-post",
                "quest-daily-tab-immediate-before",
                "quest-daily-tab-immediate-post",
            ],
        )
        self.assertEqual(
            [tap["target_identity"] for tap in runtime.taps],
            [daily.HOME_QUEST_IDENTITY, daily.QUEST_DAILY_IDENTITY],
        )
        self.assertEqual(runtime.taps[0]["target_roi"], (127, 1118, 241, 1204))
        self.assertEqual(runtime.taps[1]["target_roi"], (304, 74, 492, 146))
        self.assertEqual(
            set(result["frames"]),
            {
                "source",
                "home_immediate_before",
                "quest_successor",
                "daily_immediate_before",
                "daily_terminal",
            },
        )
        self.assertEqual(
            [row["label"] for row in result["actions"]],
            [daily.HOME_QUEST_IDENTITY, daily.QUEST_DAILY_IDENTITY],
        )

    def test_unknown_quest_successor_stops_without_second_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = ScriptedRecognizer(selected_daily=False)
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=recognizer,
                )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(len(runtime.taps), 1)
        self.assertNotIn(daily.QUEST_DAILY_IDENTITY, [tap["target_identity"] for tap in runtime.taps])
        self.assertNotIn("daily_terminal", result["frames"])
        self.assertEqual(result["resource_affecting_inputs"], 0)
        self.assertEqual(result["combat_confirmations"], 0)

    def test_stale_immediate_before_stops_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = FakeRuntime(root, stale=True)
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=ScriptedRecognizer(),
                )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(len(runtime.taps), 0)
        self.assertIn("stale", result["reason"])

    def _run_with_full_frame_modal(self, modal_full_calls: set[int]):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = VisualFakeRuntime(root)
            recognizer = daily.DailyRowClaimRecognizer(
                ocr=ModalOCR(modal_full_calls)
            )
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=recognizer,
                )
            return result, runtime

    def test_full_frame_modal_blocks_first_tap_with_valid_home_ocr(self) -> None:
        result, runtime = self._run_with_full_frame_modal({1})

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(runtime.taps, [])
        self.assertIn("full-frame overlay/modal detected", result["reason"])

    def test_full_frame_modal_blocks_second_tap_with_valid_daily_ocr(self) -> None:
        result, runtime = self._run_with_full_frame_modal({3})

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(
            [tap["target_identity"] for tap in runtime.taps],
            [daily.HOME_QUEST_IDENTITY],
        )
        self.assertIn("full-frame overlay/modal detected", result["reason"])


class DailyRowRecognizerTests(unittest.TestCase):
    @staticmethod
    def _ocr_for(tokens: list[tuple[str, int, int, int, int]]):
        def ocr(_image: np.ndarray):
            return {
                "text": [item[0] for item in tokens],
                "left": [item[1] for item in tokens],
                "top": [item[2] for item in tokens],
                "width": [item[3] for item in tokens],
                "height": [item[4] for item in tokens],
                "conf": ["95"] * len(tokens),
            }

        return ocr

    def test_home_and_quest_targets_are_derived_from_current_ocr_geometry(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.rectangle(frame, (160, 1080), (310, 1240), (0, 180, 255), -1)
        home = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("quest", 400, 200, 140, 20),
                    ("world", 600, 200, 140, 20),
                ]
            )
        ).recognize_home(frame)
        self.assertTrue(home.recognized)
        self.assertEqual(home.target_identity, daily.HOME_QUEST_IDENTITY)
        self.assertNotEqual(home.target_roi, (250, 1130, 410, 1280))
        self.assertTrue(home.target_roi[0] < 220 < home.target_roi[2])

        cv2.rectangle(frame, (240, 40), (560, 185), (0, 180, 255), -1)
        quest = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("quest", 340, 10, 70, 20),
                    ("daily", 820, 70, 140, 20),
                ]
            )
        ).recognize_quest(frame)
        self.assertTrue(quest.recognized)
        self.assertEqual(quest.target_identity, daily.QUEST_DAILY_IDENTITY)
        self.assertTrue(quest.target_roi[0] < 410 < quest.target_roi[2])

    def test_selected_daily_requires_spatial_main_comparison(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.rectangle(frame, (360, 55), (520, 145), (0, 210, 255), -1)
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("main", 100, 70, 70, 20),
                    ("daily", 820, 70, 140, 20),
                ]
            )
        ).recognize_daily_selected(frame)
        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.state, daily.DAILY_SELECTED_STATE)
        self.assertGreater(
            recognition.visual_evidence["selected_margin"],
            0.015,
        )

    def test_catalog_parser_exposes_frozen_command_bindings(self) -> None:
        parsed = pnsctl.parser().parse_args(
            [
                "development-session",
                "daily-row-reconnaissance",
                "--max-inputs",
                "2",
                "--delegated-receipt",
                "receipt.sqlite3",
                "--agent-identity",
                "luna-agent",
                "--task-id",
                "daily-row-claim",
                "--flow-id",
                "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                "--scenario",
                "selected-daily-row-evidence",
                "--variant",
                "home-quest-daily",
            ]
        )
        self.assertEqual(parsed.development_command, "daily-row-reconnaissance")
        self.assertEqual(parsed.max_inputs, 2)
        self.assertEqual(parsed.task_id, "daily-row-claim")


class PnsctlDailyRowCommandTests(unittest.TestCase):
    def test_receipt_bound_command_records_observed_terminal_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            command = [
                "development-session",
                "daily-row-reconnaissance",
                "--max-inputs",
                "2",
                "--delegated-receipt",
                str(state),
                "--agent-identity",
                "luna-agent",
                "--task-id",
                "daily-row-claim",
                "--flow-id",
                "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                "--scenario",
                "selected-daily-row-evidence",
                "--variant",
                "home-quest-daily",
            ]
            controller = control.DelegatedRuntimeReceiptController(state)
            controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
            controller.issue(
                task_id="daily-row-claim",
                flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                receipt_class="reconnaissance",
                agent_identity="luna-agent",
                command_argv=command,
                scenario="selected-daily-row-evidence",
                variant="home-quest-daily",
                permitted_action_identities=["home-quest-entry", "quest-daily-tab"],
                permitted_action_classes=["navigation", "navigation"],
                consequence_class="navigation_only",
                max_total_inputs=2,
                max_resource_affecting_inputs=0,
                max_combat_confirmations=0,
                permitted_terminal_states=["observed", "evidence_required"],
                result_identity=pnsctl.DAILY_ROW_RECON_RESULT_IDENTITY,
            )

            def connect(**kwargs):
                return FakeRuntime(Path(kwargs["output_directory"]))

            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                control,
                "DelegatedRuntimeReceiptController",
                return_value=controller,
            ), patch.object(
                LocalBlueStacksRuntime,
                "connect",
                side_effect=connect,
            ), patch.object(
                daily,
                "DailyRowClaimRecognizer",
                return_value=ScriptedRecognizer(),
            ), patch.object(
                boundary,
                "RUNTIME_INPUT_LOCK_PATH",
                root / "lock.sqlite3",
            ):
                output = pnsctl.development_session_daily_row_reconnaissance(
                    max_inputs=2,
                    delegated_receipt=state,
                    agent_identity="luna-agent",
                    task_id="daily-row-claim",
                    flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                    scenario="selected-daily-row-evidence",
                    variant="home-quest-daily",
                    command_argv=command,
                )

            result = json.loads(output)
            self.assertEqual(result["status"], "observed")
            self.assertEqual(result["input_count"], 2)
            self.assertTrue(result["ownership_released"])
            self.assertEqual(controller.inspect()["status"], "consumed")
            connection = controller._connection()
            try:
                terminal = connection.execute(
                    "SELECT status FROM delegated_results WHERE receipt_id=?",
                    (result["receipt_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(terminal[0], "observed")

    def test_daily_recon_failure_records_terminal_before_fallback_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "receipts.sqlite3"
            command = [
                "development-session",
                "daily-row-reconnaissance",
                "--max-inputs",
                "2",
                "--delegated-receipt",
                str(state),
                "--agent-identity",
                "luna-agent",
                "--task-id",
                "daily-row-claim",
                "--flow-id",
                "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                "--scenario",
                "selected-daily-row-evidence",
                "--variant",
                "home-quest-daily",
            ]
            controller = control.DelegatedRuntimeReceiptController(state)
            controller._candidate = lambda: ("head", "fingerprint")  # type: ignore[method-assign]
            receipt = controller.issue(
                task_id="daily-row-claim",
                flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                receipt_class="reconnaissance",
                agent_identity="luna-agent",
                command_argv=command,
                scenario="selected-daily-row-evidence",
                variant="home-quest-daily",
                permitted_action_identities=["home-quest-entry", "quest-daily-tab"],
                permitted_action_classes=["navigation", "navigation"],
                consequence_class="navigation_only",
                max_total_inputs=2,
                max_resource_affecting_inputs=0,
                max_combat_confirmations=0,
                permitted_terminal_states=["observed", "evidence_required"],
                result_identity=pnsctl.DAILY_ROW_RECON_RESULT_IDENTITY,
            )

            with patch.object(
                pnsctl, "DEVELOPMENT_SESSION_ROOT", root / "sessions"
            ), patch.object(
                pnsctl, "DEVELOPMENT_CHECKPOINT_PATHS", ()
            ), patch.object(
                control,
                "DelegatedRuntimeReceiptController",
                return_value=controller,
            ), patch.object(
                LocalBlueStacksRuntime,
                "connect",
                side_effect=pnsctl.OperatorError("observation failed"),
            ), patch.object(
                pnsctl,
                "_write_daily_recon_artifacts",
                side_effect=OSError("fallback artifact write failed"),
            ), patch.object(
                boundary,
                "RUNTIME_INPUT_LOCK_PATH",
                root / "lock.sqlite3",
            ):
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "observation failed"
                ):
                    pnsctl.development_session_daily_row_reconnaissance(
                        max_inputs=2,
                        delegated_receipt=state,
                        agent_identity="luna-agent",
                        task_id="daily-row-claim",
                        flow_id="DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION",
                        scenario="selected-daily-row-evidence",
                        variant="home-quest-daily",
                        command_argv=command,
                    )

            connection = controller._connection()
            try:
                terminal = connection.execute(
                    "SELECT status, payload_json FROM delegated_results WHERE receipt_id=?",
                    (receipt["receipt_id"],),
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNotNone(terminal)
            self.assertEqual(terminal[0], "evidence_required")
            self.assertEqual(json.loads(terminal[1])["status"], "evidence_required")
            with self.assertRaisesRegex(control.FlowDeliveryError, "terminal result"):
                controller.record_result(
                    receipt,
                    status="observed",
                    result_identity=pnsctl.DAILY_ROW_RECON_RESULT_IDENTITY,
                    payload={},
                )


if __name__ == "__main__":
    unittest.main()
