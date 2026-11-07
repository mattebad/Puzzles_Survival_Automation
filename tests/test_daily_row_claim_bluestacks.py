from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from typing import Callable
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import daily_row_claim_bluestacks as daily
from scripts import navigation_development_boundary as boundary
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.home_nav_recognition import NAV_STRIP_BOX, _load_template
from tests.support.capability_firewall import Clock


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
    HOME_COMPONENT = (180, 1028, 231, 1078)

    def capture(self, label: str) -> CapturedNativeFrame:
        self.labels.append(label)
        image = np.zeros((1280, 800, 3), dtype=np.uint8)
        if label in {"home-source", "home-quest-entry-immediate-before"}:
            x0, y0, x1, y1 = NAV_STRIP_BOX
            image[y0:y1, x0:x1] = _load_template()
        else:
            cv2.rectangle(image, (0, 60), (267, 145), (0, 180, 255), -1)
            cv2.rectangle(image, (268, 60), (533, 145), (70, 70, 70), -1)
            cv2.rectangle(image, (534, 60), (799, 145), (70, 70, 70), -1)
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
                    ("world", 80, 160, 80, 40),
                    ("quest", 360, 160, 100, 40),
                    ("hero", 640, 160, 80, 40),
                ]
            )
        return self._data(
            [
                ("daily", 640, 136, 140, 56),
                ("quest", 804, 138, 160, 48),
                ("alliance", 1236, 114, 190, 36),
                ("activity", 1248, 168, 172, 44),
                ("Recom'd", 672, 288, 256, 52),
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


class LabelSettlingRecognizer(ScriptedRecognizer):
    def __init__(
        self,
        *,
        quest_ready_label: str | None = None,
        daily_ready_label: str | None = None,
    ) -> None:
        super().__init__(selected_daily=True)
        self.quest_ready_after = (
            2 if quest_ready_label == "home-quest-entry-poll-01" else 999
            if quest_ready_label is not None
            else 1
        )
        self.daily_ready_after = (
            2 if daily_ready_label == "quest-daily-tab-poll-01" else 999
            if daily_ready_label is not None
            else 1
        )

    def recognize_quest(self, frame: np.ndarray) -> daily.FrameRecognition:
        self.quest_calls = getattr(self, "quest_calls", 0) + 1
        if self.quest_calls <= self.quest_ready_after:
            if self.quest_calls < self.quest_ready_after:
                return self._recognition(daily.UNKNOWN_STATE, None, None)
        return self._recognition(
            daily.QUEST_STATE,
            daily.QUEST_DAILY_IDENTITY,
            (304, 74, 492, 146),
        )


    def recognize_daily_selected(self, frame: np.ndarray) -> daily.FrameRecognition:
        if getattr(self, "quest_calls", 0) < self.quest_ready_after:
            return self._recognition(daily.UNKNOWN_STATE, None, None)
        self.daily_calls = getattr(self, "daily_calls", 0) + 1
        if self.daily_calls <= self.daily_ready_after:
            if self.daily_calls < self.daily_ready_after:
                return self._recognition(daily.UNKNOWN_STATE, None, None)
        return self._recognition(
            daily.DAILY_SELECTED_STATE,
            "daily-quest-selected",
            (326, 78, 486, 152),
        )


class DailyRowReconnaissanceTests(unittest.TestCase):
    def _session(self, root: Path) -> boundary.DevelopmentSession:
        return boundary.DevelopmentSession(
            owner="test-daily-row-recon",
            invocation_id="test-daily-row-recon",
            session_directory=root / "session",
            max_inputs=2,
        )

    def test_home_entry_resumes_selected_daily_without_redundant_tab_tap(self) -> None:
        fixtures = Path(__file__).resolve().parent / "fixtures" / "daily_rewards_native"
        home = cv2.imread(str(fixtures / "native-home-compact-footer.png"))
        selected = cv2.imread(str(fixtures / "native-daily-selected-ready-first-chest.png"))

        class DirectDailyRuntime(FakeRuntime):
            def capture(self, label: str) -> CapturedNativeFrame:
                self.labels.append(label)
                image = home if label in {
                    "home-source", "home-quest-entry-immediate-before"
                } else selected
                return _frame(self.session, label, image=image)

        def replay_tab_ocr(image: np.ndarray) -> dict[str, list[object]]:
            # Retained native header OCR missed the stylized Daily title. The
            # real selected-tab geometry must prove it between Main and Alliance.
            if image.shape[0] != 390:
                return ModalOCR._data([])
            return ModalOCR._data([
                ("main", 178, 114, 120, 42),
                ("quest", 320, 116, 148, 46),
                ("alliance", 1192, 96, 172, 36),
                ("activity", 1202, 140, 158, 44),
            ])

        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = DirectDailyRuntime(root)
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=daily.DailyRowClaimRecognizer(ocr=replay_tab_ocr),
                )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(
            [tap["target_identity"] for tap in runtime.taps],
            [daily.HOME_QUEST_IDENTITY],
        )
        self.assertEqual(
            result["recognitions"]["daily_terminal"]["state"],
            daily.DAILY_SELECTED_STATE,
        )

    def test_dispatched_home_quest_center_is_inside_rendered_component(self) -> None:
        def ocr(image: np.ndarray) -> dict[str, list[object]]:
            if image.shape[0] != 560:
                return {
                    "text": [],
                    "left": [],
                    "top": [],
                    "width": [],
                    "height": [],
                    "conf": [],
                }
            return {
                "text": [],
                "left": [],
                "top": [],
                "width": [],
                "height": [],
                "conf": [],
            }

        home_recognizer = daily.DailyRowClaimRecognizer(ocr=ocr)

        class HomeGeometryRecognizer(ScriptedRecognizer):
            def recognize_home(self, frame: np.ndarray) -> daily.FrameRecognition:
                return home_recognizer.recognize_home(frame)

        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ):
            root = Path(directory)
            runtime = VisualFakeRuntime(root)
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime,
                    session,
                    recognizer=HomeGeometryRecognizer(),
                )

        self.assertEqual(result["status"], "observed")
        target = runtime.taps[0]["target_roi"]
        self.assertEqual(target, (291, 1223, 351, 1271))
        self.assertEqual(
            (target[0] + target[2]) // 2,
            321,
        )
        self.assertEqual(
            (target[1] + target[3]) // 2,
            1247,
        )

    def test_unknown_quest_successor_stops_without_second_input(self) -> None:
        clock = Clock(time.monotonic())
        started = clock.value
        settle_successor = daily._settle_successor

        def settle_with_virtual_time(*args, **kwargs):
            with patch.object(daily, "time", SimpleNamespace(monotonic=clock, sleep=clock.advance)):
                return settle_successor(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ), patch.object(daily, "_settle_successor", side_effect=settle_with_virtual_time):
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
        self.assertEqual(clock.value - started, daily.SUCCESSOR_POLL_TIMEOUT_SECONDS)
        self.assertLessEqual(len(result["polls"]), daily.SUCCESSOR_POLL_MAX_ATTEMPTS + 1)

    def test_delayed_quest_successor_polls_without_repeating_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ), patch.object(daily, "SUCCESSOR_POLL_INTERVAL_SECONDS", 0.0), patch.object(
            daily, "SUCCESSOR_POLL_TIMEOUT_SECONDS", 1.0
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = LabelSettlingRecognizer(
                quest_ready_label="home-quest-entry-poll-01"
            )
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(
            [tap["target_identity"] for tap in runtime.taps],
            [daily.HOME_QUEST_IDENTITY, daily.QUEST_DAILY_IDENTITY],
        )
        self.assertEqual(
            [poll["label"] for poll in result["polls"] if poll["action_identity"] == daily.HOME_QUEST_IDENTITY],
            ["home-quest-entry-immediate-post", "home-quest-entry-poll-01"],
        )

    def test_delayed_daily_successor_polls_without_repeating_daily(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ), patch.object(daily, "SUCCESSOR_POLL_INTERVAL_SECONDS", 0.0), patch.object(
            daily, "SUCCESSOR_POLL_TIMEOUT_SECONDS", 1.0
        ):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = LabelSettlingRecognizer(
                daily_ready_label="quest-daily-tab-poll-01"
            )
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(len(runtime.taps), 2)
        self.assertEqual(
            [poll["label"] for poll in result["polls"] if poll["action_identity"] == daily.QUEST_DAILY_IDENTITY],
            ["quest-daily-tab-immediate-post", "quest-daily-tab-poll-01"],
        )

    def test_poll_timeout_does_not_dispatch_an_extra_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            boundary, "RUNTIME_INPUT_LOCK_PATH", Path(directory) / "lock.sqlite3"
        ), patch.object(daily, "SUCCESSOR_POLL_INTERVAL_SECONDS", 0.0), patch.object(
            daily, "SUCCESSOR_POLL_TIMEOUT_SECONDS", 1.0
        ), patch.object(daily, "SUCCESSOR_POLL_MAX_ATTEMPTS", 2):
            root = Path(directory)
            runtime = FakeRuntime(root)
            recognizer = LabelSettlingRecognizer(
                daily_ready_label="never-observed"
            )
            with self._session(root) as session:
                result = daily.run_daily_row_reconnaissance(
                    runtime, session, recognizer=recognizer
                )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(len(runtime.taps), 2)
        self.assertEqual(
            len(
                [
                    poll
                    for poll in result["polls"]
                    if poll["action_identity"] == daily.QUEST_DAILY_IDENTITY
                ]
            ),
            3,
        )

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

    @staticmethod
    def _quest_ocr(
        *,
        shift_x: int = 0,
        shift_y: int = 0,
        context_text: str = "Recom’d",
        tokens: list[tuple[str, tuple[int, int, int, int]]] | None = None,
        extra_tokens: list[tuple[str, tuple[int, int, int, int]]] | None = None,
    ):
        # Hand-authored native geometry converted through an independent OCR
        # crop model; these fixtures do not import production ROIs.
        native_tokens: list[tuple[str, tuple[int, int, int, int]]] = tokens or [
            ("Daily", (320 + shift_x, 103 + shift_y, 390 + shift_x, 131 + shift_y)),
            ("Quest", (402 + shift_x, 104 + shift_y, 482 + shift_x, 128 + shift_y)),
            ("Alliance", (618 + shift_x, 92 + shift_y, 713 + shift_x, 110 + shift_y)),
            ("Activity", (624 + shift_x, 119 + shift_y, 710 + shift_x, 141 + shift_y)),
            (context_text, (336 + shift_x, 179 + shift_y, 464 + shift_x, 205 + shift_y)),
        ]
        if extra_tokens:
            native_tokens.extend(extra_tokens)

        def scaled(item: tuple[str, tuple[int, int, int, int]]) -> tuple[str, int, int, int, int]:
            text, (x0, y0, x1, y1) = item
            return text, x0 * 2, (y0 - 35) * 2, (x1 - x0) * 2, (y1 - y0) * 2

        return DailyRowRecognizerTests._ocr_for([scaled(item) for item in native_tokens])


    @staticmethod
    def _quest_frame(*, shift_x: int = 0, shift_y: int = 0, daily_selected: bool = False) -> np.ndarray:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        y0, y1 = 60 + shift_y, 145 + shift_y
        main_color = (70, 70, 70) if daily_selected else (0, 180, 255)
        daily_color = (0, 180, 255) if daily_selected else (70, 70, 70)
        cv2.rectangle(frame, (shift_x, y0), (267 + shift_x, y1), main_color, -1)
        cv2.rectangle(frame, (268 + shift_x, y0), (533 + shift_x, y1), daily_color, -1)
        cv2.rectangle(frame, (534 + shift_x, y0), (799 + shift_x, y1), (70, 70, 70), -1)
        return frame

    def test_template_home_adapter_uses_fixed_quest_point_without_navigation_ocr(self) -> None:
        portable = Path(__file__).resolve().parent / "fixtures" / "resource_effect_authority" / "portable"
        fixtures = (
            ("session-2-terminal-home.png", True),
            ("session-1-transport-source.png", False),
        )
        for name, expected_home in fixtures:
            frame = cv2.imread(str(portable / name))
            self.assertIsNotNone(frame)
            assert frame is not None
            recognition = daily.DailyRowClaimRecognizer(
                ocr=self._ocr_for([])
            ).recognize_home(frame)
            self.assertEqual(recognition.recognized, expected_home, name)
            if expected_home:
                self.assertEqual(recognition.target_roi, (291, 1223, 351, 1271))
                self.assertEqual(
                    recognition.visual_evidence["template_home"]["quest_tap_point"],
                    (321, 1247),
                )
                self.assertEqual(
                    recognition.visual_evidence["template_home"]["recognized"],
                    True,
                )
            else:
                self.assertIsNone(recognition.target_roi)
                self.assertFalse(
                    recognition.visual_evidence["template_home"]["recognized"]
                )

    def test_selected_daily_requires_spatial_main_comparison(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.rectangle(frame, (360, 55), (520, 145), (0, 210, 255), -1)
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("main", 100, 70, 70, 20),
                    ("daily", 820, 70, 140, 20),
                    ("alliance", 1240, 70, 140, 20),
                ]
            )
        ).recognize_daily_selected(frame)
        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.state, daily.DAILY_SELECTED_STATE)
        self.assertGreater(
            recognition.visual_evidence["selected_margin"],
            0.015,
        )

    def test_selected_daily_fallback_rejects_disassociated_alliance_row(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.rectangle(frame, (170, 52), (620, 150), (0, 210, 255), -1)
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._ocr_for(
                [
                    ("main", 100 * 2, (70 - 35) * 2, 70 * 2, 20 * 2),
                    ("alliance", 620 * 2, (180 - 35) * 2, 140 * 2, 20 * 2),
                ]
            )
        ).recognize_daily_selected(frame)

        self.assertFalse(recognition.recognized)
        self.assertEqual(recognition.state, daily.UNKNOWN_STATE)
        self.assertGreater(recognition.visual_evidence["selected_margin"], 0.02)
        self.assertFalse(recognition.visual_evidence["tab_row_compatible"])
        self.assertEqual(
            recognition.visual_evidence["reason"],
            "main-alliance-tab-row-is-vertically-incompatible",
        )

    def test_retained_selected_daily_uses_center_tab_without_daily_ocr(self) -> None:
        navigation = Path(__file__).resolve().parents[1] / "tasks" / "assets" / "navigation" / "800x1280"
        daily_path = navigation / "daily_praise_claim.png"
        main_path = navigation / "daily_postreset.png"

        def retained_tab_context_ocr(image: np.ndarray) -> dict[str, list[object]]:
            if image.shape[0] == daily.NATIVE_HEIGHT * 2:
                tokens: list[tuple[str, int, int, int, int]] = []
            else:
                tokens = [
                    ("Main", 42 * 2, (83 - 35) * 2, (172 - 42) * 2, (103 - 83) * 2),
                    (
                        "Alliance",
                        493 * 2,
                        (74 - 35) * 2,
                        (594 - 493) * 2,
                        (94 - 74) * 2,
                    ),
                    (
                        "Activity",
                        493 * 2,
                        (96 - 35) * 2,
                        (594 - 493) * 2,
                        (114 - 96) * 2,
                    ),
                ]
            return {
                "text": [item[0] for item in tokens],
                "left": [item[1] for item in tokens],
                "top": [item[2] for item in tokens],
                "width": [item[3] for item in tokens],
                "height": [item[4] for item in tokens],
                "conf": ["95"] * len(tokens),
            }

        daily_frame = cv2.imread(str(daily_path))
        main_frame = cv2.imread(str(main_path))
        self.assertIsNotNone(daily_frame)
        self.assertIsNotNone(main_frame)
        assert daily_frame is not None
        assert main_frame is not None

        recognizer = daily.DailyRowClaimRecognizer(ocr=retained_tab_context_ocr)
        selected = recognizer.recognize_daily_selected(daily_frame)
        self.assertTrue(selected.recognized)
        self.assertEqual(selected.state, daily.DAILY_SELECTED_STATE)
        self.assertNotIn("daily", selected.ocr_text.split())
        self.assertGreater(selected.visual_evidence["selected_margin"], 0.02)

        main = recognizer.recognize_daily_selected(main_frame)
        self.assertFalse(main.recognized)
        self.assertEqual(main.state, daily.UNKNOWN_STATE)
        self.assertLessEqual(main.visual_evidence["selected_margin"], 0.02)

    def test_quest_recognizes_split_context_without_stylized_title(self) -> None:
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr()
        ).recognize_quest(self._quest_frame())

        self.assertTrue(recognition.recognized)
        self.assertIsNone(recognition.visual_evidence["quest_header"])
        self.assertTrue(recognition.visual_evidence["selection_proven"])


    def test_quest_accepts_normalized_recommend_spelling(self) -> None:
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr(context_text="Recommend")
        ).recognize_quest(self._quest_frame())

        self.assertTrue(recognition.recognized)

    def test_quest_spatial_semantics_translate_with_current_layout(self) -> None:
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr(shift_x=100, shift_y=15)
        ).recognize_quest(self._quest_frame(shift_x=100, shift_y=15))

        self.assertTrue(recognition.recognized)
        self.assertGreater(recognition.target_roi[0], 300)

    def test_quest_rejects_missing_or_disassociated_context(self) -> None:
        cases = [
            (
                "missing_activity",
                [
                    ("Daily", (320, 103, 390, 131)),
                    ("Quest", (402, 104, 482, 128)),
                    ("Alliance", (618, 92, 713, 110)),
                    ("Recom’d", (336, 179, 464, 205)),
                ],
            ),
            (
                "quest_far_from_daily",
                [
                    ("Daily", (320, 103, 390, 131)),
                    ("Quest", (560, 104, 640, 128)),
                    ("Alliance", (618, 92, 713, 110)),
                    ("Activity", (624, 119, 710, 141)),
                    ("Recom’d", (336, 179, 464, 205)),
                ],
            ),
            (
                "context_elsewhere",
                [
                    ("Daily", (320, 103, 390, 131)),
                    ("Quest", (402, 104, 482, 128)),
                    ("Alliance", (618, 92, 713, 110)),
                    ("Activity", (624, 119, 710, 141)),
                    ("Recommend", (620, 179, 748, 205)),
                ],
            ),
            (
                "fragmented_context",
                [
                    ("Daily", (320, 103, 390, 131)),
                    ("Quest", (402, 104, 482, 128)),
                    ("Alliance", (618, 92, 713, 110)),
                    ("Activity", (624, 119, 710, 141)),
                    ("Recom", (336, 179, 425, 205)),
                    ("d", (430, 179, 464, 205)),
                ],
            ),
        ]
        for name, tokens in cases:
            with self.subTest(case=name):
                recognition = daily.DailyRowClaimRecognizer(
                    ocr=self._quest_ocr(tokens=tokens)
                ).recognize_quest(self._quest_frame())
                self.assertFalse(recognition.recognized)

    def test_quest_rejects_selected_daily_visual_state(self) -> None:
        recognition = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr()
        ).recognize_quest(self._quest_frame(daily_selected=True))

        self.assertFalse(recognition.recognized)
        self.assertEqual(recognition.reason, "main-quest-selection-not-proven")
        self.assertLess(
            recognition.visual_evidence["main_selected_margin"],
            0.015,
        )

    def test_quest_rejects_duplicate_daily_target_and_unrelated_text(self) -> None:
        duplicate = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr(
                extra_tokens=[("Daily", (120, 103, 190, 131))]
            )
        ).recognize_quest(self._quest_frame())
        self.assertFalse(duplicate.recognized)

        unrelated = daily.DailyRowClaimRecognizer(
            ocr=self._quest_ocr(
                extra_tokens=[("Recommend", (700, 179, 790, 205))]
            )
        ).recognize_quest(self._quest_frame())
        self.assertFalse(unrelated.recognized)


class DailyClaimRecognitionTests(unittest.TestCase):
    @staticmethod
    def _ocr_for_native_tokens(
        tokens: list[tuple[str, tuple[int, int, int, int]]],
    ):
        def ocr(_image: np.ndarray) -> dict[str, list[object]]:
            return {
                "text": [text for text, _roi in tokens],
                "left": [roi[0] * 2 for _text, roi in tokens],
                "top": [roi[1] * 2 for _text, roi in tokens],
                "width": [(roi[2] - roi[0]) * 2 for _text, roi in tokens],
                "height": [(roi[3] - roi[1]) * 2 for _text, roi in tokens],
                "conf": ["95"] * len(tokens),
            }

        return ocr

    @classmethod
    def _claim_fixture(
        cls,
        *,
        row_y: int = 450,
        selected_tab: str = "daily",
        include_daily_title: bool = True,
        objective: str = "Consume",
        quantity: str = "20",
        progress: str = "36 20",
        reward: str = "Reward Pts +5",
        claim_tokens: tuple[tuple[str, tuple[int, int, int, int]], ...] | None = None,
        extra_tokens: tuple[tuple[str, tuple[int, int, int, int]], ...] = (),
        include_reset: bool = True,
        reset_timer: str = "04:00:00",
        cost_icon: bool = False,
        points: int | None = 0,
    ) -> tuple[np.ndarray, Callable[[np.ndarray], dict[str, list[object]]], list[tuple[str, tuple[int, int, int, int]]]]:
        tokens: list[tuple[str, tuple[int, int, int, int]]] = [
            ("Main", (80, 80, 170, 110)),
            ("Alliance", (500, 80, 610, 110)),
            ("Activity", (505, 115, 610, 140)),
        ]
        if points is not None:
            tokens.append((f"Daily Quest Pts {points}", (80, 220, 240, 250)))
        if include_daily_title:
            tokens.insert(1, ("Daily", (280, 80, 370, 110)))
        if include_reset:
            tokens.append((f"Reset {reset_timer}", (500, 220, 730, 250)))
        objective_y = row_y
        tokens.extend(
            [
                (objective, (100, objective_y, 190, objective_y + 25)),
                (quantity, (200, objective_y, 220, objective_y + 25)),
                ("Stamina" if objective == "Consume" else "Food", (230, objective_y, 320, objective_y + 25)),
                (progress, (330, objective_y, 410, objective_y + 25)),
                (reward, (350, objective_y + 40, 510, objective_y + 65)),
            ]
        )
        if claim_tokens is None:
            claim_tokens = (("Claim", (650, objective_y + 30, 710, objective_y + 60)),)
        tokens.extend(claim_tokens)
        tokens.extend(extra_tokens)

        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        panel_top = max(350, objective_y - 20)
        panel_bottom = min(1270, objective_y + 95)
        cv2.rectangle(
            frame,
            (70, panel_top),
            (780, panel_bottom),
            (45, 45, 45),
            -1,
        )
        cv2.rectangle(
            frame,
            (70, panel_top),
            (780, panel_bottom),
            (120, 120, 120),
            2,
        )
        if selected_tab == "daily":
            cv2.rectangle(frame, (250, 55), (430, 145), (0, 210, 255), -1)
            cv2.rectangle(frame, (50, 55), (220, 145), (70, 70, 70), -1)
        elif selected_tab == "main":
            cv2.rectangle(frame, (50, 55), (220, 145), (0, 210, 255), -1)
            cv2.rectangle(frame, (250, 55), (430, 145), (70, 70, 70), -1)
        else:
            cv2.rectangle(frame, (50, 55), (220, 145), (70, 70, 70), -1)
            cv2.rectangle(frame, (250, 55), (430, 145), (70, 70, 70), -1)
        for _claim_text, claim_roi in claim_tokens:
            cv2.rectangle(
                frame,
                (claim_roi[0] - 10, claim_roi[1] - 5),
                (claim_roi[2] + 10, claim_roi[3] + 5),
                (0, 180, 255),
                -1,
            )
        if cost_icon:
            cv2.circle(frame, (580, objective_y + 45), 12, (0, 220, 180), -1)
        return frame, cls._ocr_for_native_tokens(tokens), tokens

    def test_aggregate_claim_uses_current_free_control_without_objective_attribution(self):
        frame, ocr, _tokens = self._claim_fixture()
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.state, "DAILY_SELECTED")
        self.assertEqual(recognition.target_identity, "daily-quest-claim")
        self.assertEqual(recognition.target_roi, (640, 475, 721, 516))
        evidence = recognition.visual_evidence
        self.assertNotIn("objective_key", evidence)
        self.assertNotIn("objective_name", evidence)
        self.assertNotIn("current_progress", evidence)
        self.assertNotIn("required_progress", evidence)
        self.assertNotIn("reward_points", evidence)
        self.assertEqual(evidence["points"], 0)
        self.assertEqual(evidence["row_bounds"], (70, 432, 780, 542))
        self.assertEqual(evidence["claim_roi"], (640, 475, 721, 516))
        self.assertEqual(
            evidence["game_day_id"],
            "reset-deadline:2026-08-16T04:00:00Z",
        )

        observation = daily.daily_claim_observation_from_recognition(
            recognition,
            source_frame_sha256="b" * 64,
            evidence_ref="runtime/frames/0001-daily.png",
            game_day_id=evidence["game_day_id"],
            aggregate_batch_identity="occ:v1:test-pass-1",
        )
        self.assertIsNotNone(observation)
        self.assertFalse(observation.catalog_reconciled)
        self.assertTrue(
            __import__("tasks.available_daily_claim", fromlist=["available_daily_claim_authorizeable"])
            .available_daily_claim_authorizeable(observation)
        )

    def test_aggregate_claim_recognition_ignores_objective_and_chest_labels(self):
        frame, ocr, _tokens = self._claim_fixture(
            extra_tokens=(("Milestone Chest", (100, 500, 280, 525)),)
        )
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertTrue(recognition.visual_evidence["claim_ready"])

    def test_fake_before_claim_after_go_recognizer_pair_proves_control_exhaustion(self):
        before_frame, before_ocr, _tokens = self._claim_fixture(points=None)
        before = daily.DailyRowClaimRecognizer(ocr=before_ocr).recognize_daily_claim(
            before_frame,
            observed_utc="2026-08-16T00:00:00Z",
        )
        after_frame, after_ocr, _tokens = self._claim_fixture(
            claim_tokens=(),
            extra_tokens=(("Go", (650, 480, 710, 510)),),
            points=None,
            reset_timer="03:59:58",
        )
        cv2.rectangle(after_frame, (640, 475), (720, 515), (0, 0, 255), -1)
        after = daily.DailyRowClaimRecognizer(ocr=after_ocr).recognize_daily_claim(
            after_frame,
            observed_utc="2026-08-16T00:00:02Z",
            game_day_id=before.visual_evidence["game_day_id"],
        )

        self.assertTrue(before.recognized)
        self.assertTrue(before.visual_evidence["claim_scan_complete"])
        self.assertEqual(before.visual_evidence["recognized_claim_controls"], 1)
        self.assertTrue(after.recognized)
        self.assertEqual(after.state, daily.DAILY_SELECTED_STATE)
        self.assertIsNone(after.target_identity)
        self.assertIsNone(after.target_roi)
        self.assertTrue(after.visual_evidence["claim_scan_complete"])
        self.assertTrue(after.visual_evidence["zero_claim_scan_proven"])
        self.assertEqual(after.visual_evidence["recognized_claim_controls"], 0)
        self.assertEqual(after.visual_evidence["available_claim_controls"], 0)
        self.assertTrue(
            daily.daily_claim_postcondition_verified(
                before,
                after,
                game_day_id=before.visual_evidence["game_day_id"],
            )
        )
        points_only = replace(
            before,
            visual_evidence={**before.visual_evidence, "points": 150},
        )
        self.assertFalse(
            daily.daily_claim_postcondition_verified(
                before,
                points_only,
                game_day_id=before.visual_evidence["game_day_id"],
            )
        )

    def test_aggregate_action_key_is_restart_stable_and_batch_scoped(self):
        identity = ("account-1", "server-1", "reset-1", "day-1")
        first = daily._daily_aggregate_action_key(
            *identity, batch_identity="batch-1"
        )
        restarted = daily._daily_aggregate_action_key(
            *identity, batch_identity="batch-1"
        )
        later_batch = daily._daily_aggregate_action_key(
            *identity, batch_identity="batch-2"
        )

        self.assertEqual(first, restarted)
        self.assertNotEqual(first, later_batch)


    def test_selected_daily_title_may_be_missed_when_current_pixels_and_context_bind_center_tab(self):
        frame, ocr, _tokens = self._claim_fixture(include_daily_title=False)
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)

    def test_gold_claim_binding_does_not_require_stylized_claim_ocr(self):
        frame, _ocr, tokens = self._claim_fixture()
        ocr_without_claim = self._ocr_for_native_tokens(
            [item for item in tokens if item[0].casefold() != "claim"]
        )
        recognition = daily.DailyRowClaimRecognizer(
            ocr=ocr_without_claim
        ).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.visual_evidence["recognized_claim_controls"], 1)
        self.assertEqual(recognition.visual_evidence["claim_ocr_roi"], None)
        self.assertEqual(recognition.visual_evidence["button_evidence"]["button_class"], "ordinary_claim_button")

    def test_red_go_control_is_rejected_by_gold_hsv_binding(self):
        frame, ocr, _tokens = self._claim_fixture(
            claim_tokens=(),
            extra_tokens=(("Go", (650, 480, 710, 510)),),
        )
        cv2.rectangle(frame, (640, 475), (720, 515), (0, 0, 255), -1)
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertFalse(recognition.visual_evidence["claim_ready"])
        self.assertEqual(recognition.visual_evidence["recognized_claim_controls"], 0)
        self.assertIsNone(recognition.target_roi)

    def test_multiple_safe_claim_controls_select_one_current_control(self):
        frame, ocr, _tokens = self._claim_fixture(
            claim_tokens=(
                ("Claim", (570, 480, 610, 510)),
                ("Claim", (670, 480, 710, 510)),
            )
        )
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.target_roi, (560, 475, 621, 516))
        evidence = recognition.visual_evidence

        self.assertEqual(evidence["available_claim_controls"], 1)
        self.assertEqual(len(evidence["claim_candidates"]), 1)
        self.assertEqual(evidence["claim_candidates"][0]["status"], "eligible")

    def test_selected_current_control_with_attached_cost_blocks_without_skipping_to_another_row(self):
        frame, ocr, _tokens = self._claim_fixture(
            claim_tokens=(
                ("Claim", (570, 480, 610, 510)),
                ("Claim", (670, 480, 710, 510)),
            ),
            extra_tokens=(("Gems", (400, 500, 440, 525)),),
        )
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )

        self.assertFalse(recognition.recognized)
        self.assertIn("attached currency", recognition.reason or "")

    def test_daily_claim_rejects_main_missing_context_and_overlay_states(self):
        cases = (
            ("main_selected", self._claim_fixture(selected_tab="main")),
            ("missing_daily_semantics", self._claim_fixture(selected_tab="unknown", include_daily_title=False)),
            (
                "overlay",
                self._claim_fixture(extra_tokens=(("Confirm", (300, 300, 400, 330)),)),
            ),
            ("reset_missing", self._claim_fixture(include_reset=False)),
        )
        for name, (frame, ocr, _tokens) in cases:
            with self.subTest(case=name):
                recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
                    frame,
                    game_day_id="game-day-a",
                )
                self.assertFalse(recognition.recognized)

    def test_daily_claim_rejects_go_and_clipped_controls(self):
        cases = (
            ("go", self._claim_fixture(claim_tokens=())),
            ("clipped", self._claim_fixture(row_y=1190)),
        )
        for name, (frame, ocr, _tokens) in cases:
            with self.subTest(case=name):
                recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
                    frame,
                    game_day_id="game-day-a",
                )
                self.assertFalse(bool((recognition.visual_evidence or {}).get("claim_ready")))

    def test_daily_claim_rejects_claim_outside_measured_panel_geometry(self):
        frame, ocr, _tokens = self._claim_fixture(
            claim_tokens=(("Claim", (650, 555, 710, 585)),)
        )
        recognition = daily.DailyRowClaimRecognizer(ocr=ocr).recognize_daily_claim(
            frame,
            observed_utc="2026-08-16T00:00:00Z",
        )
        self.assertFalse(recognition.recognized)

    def test_daily_claim_rejects_numeric_only_and_icon_only_attached_costs(self):
        numeric_frame, numeric_ocr, _tokens = self._claim_fixture(
            extra_tokens=(("2", (520, 500, 560, 525)),)
        )
        icon_frame, icon_ocr, _tokens = self._claim_fixture(cost_icon=True)
        for name, frame, ocr in (
            ("numeric-only", numeric_frame, numeric_ocr),
            ("icon-only", icon_frame, icon_ocr),
        ):
            with self.subTest(case=name):
                recognition = daily.DailyRowClaimRecognizer(
                    ocr=ocr
                ).recognize_daily_claim(
                    frame,
                    observed_utc="2026-08-16T00:00:00Z",
                )
                self.assertFalse(recognition.recognized)

    def test_reset_deadline_is_bound_from_injected_wall_utc_and_rollover_rejects(self):
        before_frame, before_ocr, _tokens = self._claim_fixture(
            reset_timer="00:00:02"
        )
        before = daily.DailyRowClaimRecognizer(ocr=before_ocr).recognize_daily_claim(
            before_frame,
            observed_utc="2026-08-16T23:59:58Z",
        )
        self.assertTrue(before.recognized)
        before_evidence = before.visual_evidence
        self.assertEqual(
            before_evidence["reset_deadline_identity"],
            "reset-deadline:2026-08-17T00:00:00Z",
        )
        self.assertEqual(
            before_evidence["game_day_id"],
            before_evidence["reset_deadline_identity"],
        )

        after_frame, after_ocr, _tokens = self._claim_fixture(
            claim_tokens=(),
            extra_tokens=(("Go", (650, 480, 710, 510)),),
            reset_timer="23:59:58",
        )
        cv2.rectangle(after_frame, (640, 475), (720, 515), (0, 0, 255), -1)
        after = daily.DailyRowClaimRecognizer(ocr=after_ocr).recognize_daily_claim(
            after_frame,
            observed_utc="2026-08-17T00:00:00Z",
            game_day_id=before_evidence["game_day_id"],
        )
        self.assertFalse(
            daily.daily_claim_postcondition_verified(
                before,
                after,
                game_day_id=before_evidence["game_day_id"],
            )
        )

    def test_reset_deadline_accepts_monotonic_injected_countdown(self):
        before_frame, before_ocr, _tokens = self._claim_fixture()
        before = daily.DailyRowClaimRecognizer(ocr=before_ocr).recognize_daily_claim(
            before_frame,
            observed_utc="2026-08-16T00:00:00Z",
        )
        self.assertTrue(before.recognized)

        after_frame, after_ocr, _tokens = self._claim_fixture(
            claim_tokens=(),
            extra_tokens=(("Go", (650, 480, 710, 510)),),
            reset_timer="03:59:58",
        )
        cv2.rectangle(after_frame, (640, 475), (720, 515), (0, 0, 255), -1)
        after = daily.DailyRowClaimRecognizer(ocr=after_ocr).recognize_daily_claim(
            after_frame,
            observed_utc="2026-08-16T00:00:02Z",
            game_day_id=before.visual_evidence["game_day_id"],
        )
        self.assertTrue(
            daily.daily_claim_postcondition_verified(
                before,
                after,
                game_day_id=before.visual_evidence["game_day_id"],
            )
        )


class DailyMilestoneReadinessTests(unittest.TestCase):
    NATIVE_FIXTURE = (
        Path(__file__).parent
        / "fixtures"
        / "daily_rewards_native"
        / "native-daily-selected-ready-first-chest.png"
    )
    NATIVE_SOURCE_SHA256 = (
        "5f5388e9dfed863efdeba8580d08adf742083166f66c43f6ed8428a16593e83c"
    )

    def _native_daily_frame(self) -> tuple[bytes, np.ndarray, daily.FrameRecognition]:
        payload = self.NATIVE_FIXTURE.read_bytes()
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert image is not None
        recognition = daily.DailyRowClaimRecognizer().recognize_daily_claim(
            image,
            observed_utc="2026-11-06T21:46:23Z",
        )
        return payload, image, recognition

    def test_native_screenshot_recognizes_only_the_first_glowing_chest(self) -> None:
        payload, image, recognition = self._native_daily_frame()
        source_sha256 = hashlib.sha256(payload).hexdigest()
        self.assertEqual(source_sha256, self.NATIVE_SOURCE_SHA256)
        self.assertTrue(recognition.recognized)
        self.assertEqual(recognition.state, daily.DAILY_SELECTED_STATE)
        self.assertIsNone(recognition.target_identity)
        self.assertIsNone(recognition.target_roi)
        self.assertTrue(recognition.visual_evidence["claim_scan_complete"])
        self.assertTrue(recognition.visual_evidence["zero_claim_scan_proven"])
        self.assertEqual(recognition.visual_evidence["recognized_claim_controls"], 0)
        self.assertEqual(recognition.visual_evidence["available_claim_controls"], 0)
        scan = daily.recognize_daily_milestone_chests(
            image,
            recognition,
            source_frame_sha256=source_sha256,
        )

        self.assertEqual(scan["status"], "observed")
        self.assertEqual(scan["slot_count"], 5)
        self.assertEqual(scan["observed_chest_count"], 5)
        self.assertEqual(scan["ready_chest_count"], 1)
        self.assertEqual(
            [chest["milestone_state"] for chest in scan["milestones"]],
            ["ready", "not_ready", "not_ready", "not_ready", "not_ready"],
        )
        self.assertTrue(
            all(chest["target_roi"] is not None for chest in scan["milestones"])
        )
        self.assertEqual(scan["source_frame_sha256"], self.NATIVE_SOURCE_SHA256)

    def test_fake_points_counterfactual_does_not_change_chest_readiness(self) -> None:
        payload, image, recognition = self._native_daily_frame()
        source_sha256 = hashlib.sha256(payload).hexdigest()
        native_scan = daily.recognize_daily_milestone_chests(
            image,
            recognition,
            source_frame_sha256=source_sha256,
        )
        # This is an explicitly fake metadata-only counterfactual, not native evidence.
        fake_points_recognition = replace(
            recognition,
            visual_evidence={
                **dict(recognition.visual_evidence or {}),
                "points": 150,
            },
        )
        fake_scan = daily.recognize_daily_milestone_chests(
            image,
            fake_points_recognition,
            source_frame_sha256=source_sha256,
        )

        self.assertEqual(fake_scan["points"], 150)
        self.assertEqual(fake_scan["ready_chest_count"], 1)
        self.assertEqual(
            [chest["milestone_state"] for chest in fake_scan["milestones"]],
            [chest["milestone_state"] for chest in native_scan["milestones"]],
        )

    def test_fake_wrong_context_overlay_and_ambiguous_header_are_unknown(self) -> None:
        payload, image, recognition = self._native_daily_frame()
        source_sha256 = hashlib.sha256(payload).hexdigest()
        visual = dict(recognition.visual_evidence or {})
        selected_geometry = dict(visual["selected_daily_semantics"])
        selected_geometry["daily_candidates"] = (
            *selected_geometry["daily_candidates"],
            *selected_geometry["daily_candidates"],
        )
        ambiguous_visual = {
            **visual,
            "selected_daily_semantics": selected_geometry,
        }
        overlay_visual = {
            **visual,
            "full_frame_overlay": {
                "recognized": True,
                "markers": ("confirm",),
            },
        }
        cases = (
            ("wrong-context", replace(recognition, state=daily.HOME_STATE)),
            ("overlay", replace(recognition, visual_evidence=overlay_visual)),
            ("ambiguous-header", replace(recognition, visual_evidence=ambiguous_visual)),
        )
        for name, fake_recognition in cases:
            with self.subTest(case=name):
                scan = daily.recognize_daily_milestone_chests(
                    image,
                    fake_recognition,
                    source_frame_sha256=source_sha256,
                )
                self.assertEqual(scan["status"], "unknown")
                self.assertEqual(scan["ready_chest_count"], 0)
                self.assertEqual(
                    [chest["milestone_state"] for chest in scan["milestones"]],
                    ["unknown"] * 5,
                )

    def test_fake_no_aggregate_branch_still_reports_ready_chest_successor_gap(
        self,
    ) -> None:
        payload, image, _recognition = self._native_daily_frame()
        source_sha256 = hashlib.sha256(payload).hexdigest()
        native_frame = CapturedNativeFrame(
            image,
            payload,
            source_sha256,
            time.monotonic(),
            self.NATIVE_FIXTURE,
        )

        class FakeDailyRouteRecognizer(daily.DailyRowClaimRecognizer):
            def recognize_home(self, frame: np.ndarray) -> daily.FrameRecognition:
                return daily.FrameRecognition(
                    daily.HOME_STATE,
                    True,
                    daily.HOME_QUEST_IDENTITY,
                    (120, 1100, 240, 1200),
                )

        class FakeRuntime:
            frame_actions: tuple[object, ...] = ()

            def capture(self, _label: str) -> CapturedNativeFrame:
                return native_frame

        class FakeSession:
            def observe(self, capture, *, label: str) -> CapturedNativeFrame:
                return capture(label)

        context = SimpleNamespace(
            validate_identity=lambda: None,
            accounting=lambda: SimpleNamespace(input_count=0, verified=True),
            runtime=FakeRuntime(),
            session=FakeSession(),
            action_store=object(),
            initial_frame=native_frame,
            is_clean_home=lambda _frame: True,
            bind_initial_observation=lambda *_args, **_kwargs: None,
            utc_clock=time.time,
            monotonic_clock=time.monotonic,
            flow_id="daily-rewards-test",
            identity=SimpleNamespace(
                account_id="account",
                server_id="server",
                reset_id="reset",
                task_id="daily-rewards-test",
            ),
            occurrence_key="occ:v1:daily-rewards-test",
            invocation_id="daily-rewards-test",
            owner="daily-rewards-test",
        )
        with patch.object(daily, "DailyRowClaimRecognizer", FakeDailyRouteRecognizer), patch.object(
            daily,
            "run_daily_row_reconnaissance",
            return_value={"status": "observed"},
        ):
            result = daily.run_daily_rewards_from_home(
                context,
                {"observation_interval_seconds": 3600},
            )

        self.assertEqual(result["status"], "evidence_required")
        self.assertEqual(result["aggregate_claim"]["status"], "none")
        self.assertEqual(result["total_action_count"], 0)
        self.assertFalse(result["terminal_home_verified"])
        self.assertEqual(result["milestone_scan"]["observed_chest_count"], 5)
        self.assertEqual(result["unclaimed_ready_chest_count"], 1)
        self.assertIn("same-chest", result["reason"])
        self.assertIn("claimed, opened, or removed", result["reason"])


    def _run_fake_static_zero_claim_route(
        self,
        root: Path,
        *,
        return_home: bool,
    ) -> tuple[dict[str, object], object, object]:
        _payload, native_image, native_recognition = self._native_daily_frame()
        native_scan = daily.recognize_daily_milestone_chests(
            native_image,
            native_recognition,
            source_frame_sha256="a" * 64,
        )
        first, second = native_scan["milestones"][:2]
        fake_image = native_image.copy()
        x0, y0, x1, y1 = first["target_roi"]
        sx0, sy0, sx1, sy1 = second["target_roi"]
        self.assertEqual((x1 - x0, y1 - y0), (sx1 - sx0, sy1 - sy0))
        # Explicit fake counterfactual: copy one static chest over the glowing slot.
        fake_image[y0:y1, x0:x1] = native_image[sy0:sy1, sx0:sx1]
        fake_recognition = daily.DailyRowClaimRecognizer().recognize_daily_claim(
            fake_image,
            observed_utc="2026-11-06T21:46:23Z",
        )
        self.assertTrue(fake_recognition.recognized)
        self.assertTrue(fake_recognition.visual_evidence["zero_claim_scan_proven"])
        fake_payload_ok, fake_payload = cv2.imencode(".png", fake_image)
        self.assertTrue(fake_payload_ok)
        fake_sha = hashlib.sha256(fake_payload.tobytes()).hexdigest()
        fake_scan = daily.recognize_daily_milestone_chests(
            fake_image,
            fake_recognition,
            source_frame_sha256=fake_sha,
        )
        self.assertEqual(fake_scan["status"], "observed")
        self.assertEqual(fake_scan["ready_chest_count"], 0)
        self.assertEqual(
            [chest["milestone_state"] for chest in fake_scan["milestones"]],
            ["not_ready"] * 5,
        )

        home_image = np.zeros((1280, 800, 3), dtype=np.uint8)
        unknown_image = np.full((1280, 800, 3), 19, dtype=np.uint8)
        session_directory = root / "native-session"
        session_directory.mkdir(parents=True)

        class FakeRuntime:
            execute = True
            frame_max_age_seconds = 30.0

            def __init__(self) -> None:
                self.current_image = fake_image
                self.input_count = 0
                self.frame_actions: list[object] = []

            def capture(self, label: str) -> CapturedNativeFrame:
                return _frame(session_directory, label, image=self.current_image)

            def back(self, _source, *, action_key: str, target_identity: str) -> None:
                self.input_count += 1
                self.current_image = home_image if return_home else unknown_image

            @staticmethod
            def measure_device_state() -> str:
                return "device"

            @staticmethod
            def measure_foreground_package() -> str:
                return "com.global.ztmslg"

        class FakeSession:
            def __init__(self, runtime: FakeRuntime) -> None:
                self.runtime = runtime
                self.input_count = 0
                self.actions: list[dict[str, object]] = []
                self.session_directory = session_directory

            def observe(self, capture, *, label: str) -> CapturedNativeFrame:
                return capture(label)

            def run_action(self, **kwargs):
                before = kwargs["capture"](f"{kwargs['label']}-immediate-before")
                if kwargs.get("authorize") is not None:
                    kwargs["authorize"](before)
                self.input_count += 1
                kwargs["dispatch"](before)
                after = kwargs["capture"](f"{kwargs['label']}-immediate-post")
                state = kwargs["recognize"](after)
                if state == daily.UNKNOWN_STATE and kwargs.get("settled_successor"):
                    after = kwargs["settled_successor"]()
                    state = kwargs["recognize"](after)
                status = "completed" if state != daily.UNKNOWN_STATE else "unknown"
                self.actions.append({"label": kwargs["label"], "state": state})
                return SimpleNamespace(status=status, reason="replay")

        runtime = FakeRuntime()
        session = FakeSession(runtime)
        initial_home = _frame(
            session_directory,
            "fake-initial-home",
            image=home_image,
        )

        class FakeRouteRecognizer(daily.DailyRowClaimRecognizer):
            def recognize_home(self, frame: np.ndarray) -> daily.FrameRecognition:
                if frame is home_image:
                    return daily.FrameRecognition(
                        daily.HOME_STATE,
                        True,
                        daily.HOME_QUEST_IDENTITY,
                        (120, 1100, 240, 1200),
                    )
                return super().recognize_home(frame)

        context = SimpleNamespace(
            validate_identity=lambda: None,
            accounting=lambda: SimpleNamespace(
                input_count=session.input_count,
                verified=session.input_count == runtime.input_count,
            ),
            runtime=runtime,
            session=session,
            action_store=object(),
            initial_frame=initial_home,
            is_clean_home=lambda frame: frame is home_image,
            bind_initial_observation=lambda *_args, **_kwargs: None,
            utc_clock=time.time,
            monotonic_clock=time.monotonic,
            flow_id="daily-rewards-test",
            identity=SimpleNamespace(
                account_id="account",
                server_id="server",
                reset_id="reset",
                task_id="daily-rewards-test",
            ),
            occurrence_key="occ:v1:daily-rewards-test",
            invocation_id="daily-rewards-test",
            owner="daily-rewards-test",
            settle_seconds=0.0,
        )
        with patch.object(
            daily,
            "DailyRowClaimRecognizer",
            FakeRouteRecognizer,
        ), patch.object(
            daily,
            "run_daily_row_reconnaissance",
            return_value={"status": "observed"},
        ):
            result = daily.run_daily_rewards_from_home(
                context,
                {"observation_interval_seconds": 3600},
            )
        return result, runtime, session

    def test_fake_static_zero_claim_replay_requires_verified_home_and_projects_no_work(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, runtime, session = self._run_fake_static_zero_claim_route(
                Path(tmp),
                return_home=True,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["no_work"])
        self.assertTrue(result["terminal_home_verified"])
        self.assertTrue(result["accounting_verified"])
        self.assertEqual(result["total_action_count"], 0)
        self.assertEqual(result["aggregate_claim"]["status"], "none")
        self.assertEqual(result["milestone_scan"]["status"], "verified")
        self.assertEqual(result["milestone_scan"]["ready_chest_count"], 0)
        self.assertEqual(result["milestone_scan"]["ready_chest_keys"], [])
        static_keys = result["milestone_scan"]["static_or_locked_chest_keys"]
        self.assertEqual(len(static_keys), 5)
        self.assertEqual(len(set(static_keys)), 5)
        self.assertEqual(
            result["no_work_evidence"]["static_or_locked_chest_keys"],
            static_keys,
        )
        self.assertEqual(
            result["no_work_evidence"]["source_frame_sha256"],
            result["milestone_scan"]["source_frame_sha256"],
        )
        self.assertEqual(result["no_work_evidence"]["ordinary_claim_controls"], 0)
        self.assertEqual(runtime.input_count, session.input_count)

    def test_fake_static_zero_claim_replay_does_not_invent_home_on_unknown_successor(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, runtime, session = self._run_fake_static_zero_claim_route(
                Path(tmp),
                return_home=False,
            )

        self.assertNotEqual(result["status"], "completed")
        self.assertFalse(result["no_work"])
        self.assertFalse(result["terminal_home_verified"])
        self.assertNotIn("terminal_home_frame", result)
        self.assertIn("clean Home return", result["reason"])
        self.assertEqual(runtime.input_count, session.input_count)


if __name__ == "__main__":
    unittest.main()
