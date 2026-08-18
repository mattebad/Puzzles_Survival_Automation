"""Offline visual and operator-contract checks for Ultimate Challenge Daily."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from scripts import bluestacks_ultimate_challenge as ultimate
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from scripts import flow_delivery_ultimate_challenge_bluestacks as delivery
from scripts.flow_delivery_evidence import require_operator_evidence
from tasks.home_atlas import (
    AmbiguityState,
    AtlasViewport,
    HomeAtlas,
    LocalizationResult,
    PlatformProfile,
    SemanticBuilding,
    ZoomIdentity,
)
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, frame_digest
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

    def test_popup_detector_requires_interior_central_geometry(self) -> None:
        blank = np.zeros((1280, 800, 3), dtype=np.uint8)
        geometries = (
            ("centered", (50, 400, 750, 800), True),
            ("offset_interior", (170, 400, 730, 800), True),
            ("left_margin_touching", (40, 400, 700, 800), False),
            ("right_margin_touching", (100, 400, 760, 800), False),
            ("right_edge_scenery", (34, 588, 799, 1091), False),
            ("left_edge_scenery", (1, 588, 766, 1091), False),
        )
        for label, candidate, expected_popup in geometries:
            with self.subTest(geometry=label), patch.object(
                ultimate,
                "_visual_popup_panel_candidates",
                return_value=[candidate],
            ):
                self.assertEqual(
                    bool(ultimate._central_popup_candidates(blank)),
                    expected_popup,
                )
                self.assertEqual(
                    ultimate._unexpected_visual_popup(blank),
                    expected_popup,
                )

        with patch.object(
            ultimate,
            "_visual_popup_panel_candidates",
            return_value=[(50, 400, 750, 800)],
        ):
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


class UltimateChallengeLineupTests(unittest.TestCase):
    """Deterministic native Hero Lineup recognition and route regressions."""

    _CARD_ROIS = (
        (29, 621, 168, 808),
        (180, 620, 323, 810),
        (332, 620, 475, 810),
        (485, 620, 628, 810),
        (639, 621, 778, 808),
    )
    _CARD_GRID_CANDIDATE = (84, 373, 750, 1050)
    _GOLD = (0, 180, 220)
    _BACKGROUND = (24, 28, 36)

    @classmethod
    def _lineup_frame(
        cls,
        *,
        button: bool = True,
        obscured_card: int | None = None,
    ) -> np.ndarray:
        frame = np.full((1280, 800, 3), cls._BACKGROUND, dtype=np.uint8)
        cv2.putText(
            frame,
            "Hero Lineup",
            (210, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.25,
            (255, 255, 255),
            3,
            cv2.LINE_AA,
        )
        for index, (x0, y0, x1, y1) in enumerate(cls._CARD_ROIS):
            color = cls._BACKGROUND if index == obscured_card else cls._GOLD
            cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), color, -1)
        if button:
            cv2.rectangle(frame, (280, 1145), (520, 1265), cls._GOLD, -1)
        return frame

    @staticmethod
    def _ocr_data(
        tokens: tuple[str, ...] = ("Hero", "Lineup"),
        confidences: tuple[str, ...] = ("96", "96"),
    ) -> dict[str, list[str]]:
        return {
            "text": list(tokens),
            "conf": list(confidences),
        }

    def _bind(
        self,
        frame: np.ndarray,
        *,
        ocr_data: dict[str, list[str]] | None = None,
        popup_candidates: list[tuple[int, int, int, int]] | None = None,
    ):
        with patch.object(
            ultimate.pytesseract,
            "image_to_data",
            return_value=ocr_data or self._ocr_data(),
        ), patch.object(
            ultimate,
            "_central_popup_candidates",
            return_value=(
                [self._CARD_GRID_CANDIDATE]
                if popup_candidates is None
                else popup_candidates
            ),
        ):
            return ultimate._bind_lineup_challenge_button(frame)

    def test_native_positive_lineup_accepts_title_cards_button_and_grid_artifact(self) -> None:
        frame = self._lineup_frame()
        self.assertTrue(
            ultimate._ocr_ordered_tokens(frame, ultimate._UC_TITLE_ROI, ("hero", "lineup"))
        )
        self.assertEqual(ultimate._central_popup_candidates(frame), [])
        with patch.object(
            ultimate,
            "_unexpected_visual_popup",
            side_effect=AssertionError("Hero Lineup must not use generic popup gate"),
        ):
            bound = ultimate._bind_lineup_challenge_button(frame)

        self.assertEqual(bound, (300, 1175, 500, 1230))

    def test_lineup_grid_requires_exact_measured_allowlist(self) -> None:
        expected = {
            (84, 373, 750, 1050),
            (84, 373, 729, 1050),
            (84, 373, 715, 1050),
            (85, 435, 750, 1050),
            (101, 435, 750, 1050),
            (85, 435, 729, 1050),
            (106, 435, 750, 1050),
            (85, 435, 715, 1050),
            (101, 435, 729, 1050),
            (106, 435, 729, 1050),
            (101, 435, 715, 1050),
            (106, 435, 715, 1050),
            (84, 373, 750, 891),
            (84, 373, 748, 891),
            (85, 435, 750, 891),
            (85, 435, 748, 891),
            (101, 435, 750, 891),
            (101, 435, 748, 891),
            (106, 435, 750, 891),
            (106, 435, 748, 891),
        }
        self.assertEqual(ultimate._HERO_LINEUP_CARD_GRID_BOXES, expected)
        self.assertTrue(
            ultimate._lineup_card_grid_candidate_matches(self._CARD_GRID_CANDIDATE)
        )
        for candidate in (
            (80, 370, 750, 1050),
            (84, 373, 750, 1051),
        ):
            with self.subTest(candidate=candidate):
                self.assertFalse(
                    ultimate._lineup_card_grid_candidate_matches(candidate)
                )

    def test_lineup_title_and_visual_requirements_fail_closed(self) -> None:
        frame = self._lineup_frame()
        negative_titles = (
            ("missing", self._ocr_data(("Hero",), ("96",))),
            ("reversed", self._ocr_data(("Lineup", "Hero"), ("96", "96"))),
            ("low_confidence", self._ocr_data(("Hero", "Lineup"), ("79", "96"))),
        )
        for label, ocr_data in negative_titles:
            with self.subTest(case=label):
                self.assertIsNone(self._bind(frame, ocr_data=ocr_data))

        with self.subTest(case="missing_button"):
            self.assertIsNone(self._bind(self._lineup_frame(button=False)))
        with self.subTest(case="obscured_card"):
            self.assertIsNone(self._bind(self._lineup_frame(obscured_card=2)))

    def test_independent_lineup_modal_candidates_are_not_ignored(self) -> None:
        frame = self._lineup_frame()
        for candidate in ((170, 420, 630, 860), (60, 330, 760, 1100)):
            with self.subTest(candidate=candidate):
                self.assertIsNone(
                    self._bind(frame, popup_candidates=[candidate])
                )

    def test_other_states_retain_generic_popup_denial(self) -> None:
        blank = np.zeros((1280, 800, 3), dtype=np.uint8)
        with patch.object(
            ultimate,
            "_unexpected_visual_popup",
            return_value=True,
        ) as popup:
            self.assertIsNone(ultimate._recognize_ultimate_main(blank))
            self.assertIsNone(ultimate._recognize_active_battle(blank))
        self.assertEqual(popup.call_count, 2)

    @staticmethod
    def _captured(
        root: Path,
        frame: np.ndarray,
        label: str,
        ordinal: int,
    ) -> CapturedNativeFrame:
        encoded_ok, encoded = cv2.imencode(".png", frame)
        assert encoded_ok
        payload = encoded.tobytes()
        path = root / f"{ordinal:04d}-{label}.png"
        path.write_bytes(payload)
        return CapturedNativeFrame(
            frame=frame.copy(),
            png=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
            captured_monotonic=float(ordinal),
            path=path,
        )

    class _RouteRuntime:
        def __init__(self, root: Path, frame: np.ndarray) -> None:
            self.root = root
            self.frame = frame
            self.runner = SimpleNamespace()
            self.captures: list[CapturedNativeFrame] = []
            self.taps: list[dict[str, object]] = []
            self.reconciliations: list[
                tuple[str, str, CapturedNativeFrame, str]
            ] = []

        def capture(self, label: str) -> CapturedNativeFrame:
            captured = UltimateChallengeLineupTests._captured(
                self.root,
                self.frame,
                label,
                len(self.captures) + 1,
            )
            self.captures.append(captured)
            return captured

        def tap(self, *args, **kwargs) -> None:
            self.taps.append(kwargs)

        def reconcile(
            self,
            action_key: str,
            status: str,
            post: CapturedNativeFrame,
            reason: str,
        ) -> None:
            self.reconciliations.append((action_key, status, post, reason))

    def test_route_confirms_exact_challenge_key_against_lineup_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            session.mkdir()
            frames = session / "frames"
            frames.mkdir()
            events = session / "events.jsonl"
            runtime = self._RouteRuntime(root, self._lineup_frame())
            active = self._captured(
                root,
                np.zeros((1280, 800, 3), dtype=np.uint8),
                "active",
                101,
            )
            warning = self._captured(
                root,
                np.zeros((1280, 800, 3), dtype=np.uint8),
                "warning",
                102,
            )
            fled = self._captured(
                root,
                np.zeros((1280, 800, 3), dtype=np.uint8),
                "fled",
                103,
            )
            with patch.object(
                ultimate,
                "_recognize_ultimate_main",
                return_value=(320, 1195, 480, 1245),
            ), patch.object(
                ultimate,
                "_recognize_active_battle",
                return_value=(700, 20, 750, 75),
            ), patch.object(
                ultimate,
                "_bind_flee_warning_button",
                return_value=(470, 600, 700, 700),
            ), patch.object(
                ultimate,
                "_capture_until",
                side_effect=[active, warning, fled],
            ), patch.object(
                ultimate,
                "_run_post_flee_home_route",
                return_value=("complete_for_reset", {"reason": "test terminal"}),
            ), patch.object(
                ultimate,
                "utc_stamp",
                return_value="r16-test",
            ):
                terminal, detail = ultimate._run_daily_route(
                    runtime=runtime,
                    session=session,
                    frames=frames,
                    events=events,
                    atlas_path=root / "atlas.json",
                    reset_identity="game-day-2026-08-17",
                    maximum_pans=4,
                    post_input_delay=0,
                    entry_observation=SimpleNamespace(),
                    starting_state="ultimate_challenge",
                )

        self.assertEqual(terminal, "complete_for_reset")
        self.assertIsNone(detail.get("challenge_action_key"))
        self.assertGreaterEqual(len(runtime.reconciliations), 1)
        first_key, first_status, first_post, _reason = runtime.reconciliations[0]
        self.assertEqual(first_key, "tap_challenge-1-r16-test")
        self.assertEqual(first_status, "confirmed")
        np.testing.assert_array_equal(first_post.frame, self._lineup_frame())
        self.assertEqual(first_post, runtime.captures[2])

    def test_route_reconciles_exact_challenge_key_unresolved_on_six_failed_bindings(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            session.mkdir()
            frames = session / "frames"
            frames.mkdir()
            events = session / "events.jsonl"
            runtime = self._RouteRuntime(root, np.zeros((1280, 800, 3), dtype=np.uint8))
            with patch.object(
                ultimate,
                "_recognize_ultimate_main",
                return_value=(320, 1195, 480, 1245),
            ), patch.object(
                ultimate,
                "_bind_lineup_challenge_button",
                return_value=None,
            ), patch.object(
                ultimate.time,
                "sleep",
                return_value=None,
            ), patch.object(
                ultimate,
                "utc_stamp",
                return_value="r16-test",
            ):
                terminal, detail = ultimate._run_daily_route(
                    runtime=runtime,
                    session=session,
                    frames=frames,
                    events=events,
                    atlas_path=root / "atlas.json",
                    reset_identity="game-day-2026-08-17",
                    maximum_pans=4,
                    post_input_delay=0,
                    entry_observation=SimpleNamespace(),
                    starting_state="ultimate_challenge",
                )

            lineup_captures = runtime.captures[-6:]
            latest = lineup_captures[-1]
            self.assertEqual(len(lineup_captures), 6)
            self.assertEqual(
                {capture.sha256 for capture in lineup_captures},
                {latest.sha256},
            )
            self.assertEqual(terminal, "blocked_fail_closed")
            self.assertEqual(
                detail["challenge_action_key"],
                "tap_challenge-1-r16-test",
            )
            self.assertEqual(detail["lineup_sha256"], latest.sha256)
            self.assertEqual(detail["latest_capture_sha256"], latest.sha256)
            self.assertEqual(len(runtime.reconciliations), 1)
            key, status, post, _reason = runtime.reconciliations[0]
            self.assertEqual(key, detail["challenge_action_key"])
            self.assertEqual(status, "unresolved")
            self.assertIs(post, latest)

    def test_route_reconciles_latest_post_on_lineup_predicate_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            session.mkdir()
            frames = session / "frames"
            frames.mkdir()
            events = session / "events.jsonl"
            runtime = self._RouteRuntime(
                root,
                np.zeros((1280, 800, 3), dtype=np.uint8),
            )
            with patch.object(
                ultimate,
                "_recognize_ultimate_main",
                return_value=(320, 1195, 480, 1245),
            ), patch.object(
                ultimate,
                "_bind_lineup_challenge_button",
                side_effect=RuntimeError("synthetic predicate failure"),
            ), patch.object(
                ultimate.time,
                "sleep",
                return_value=None,
            ), patch.object(
                ultimate,
                "utc_stamp",
                return_value="r16-predicate-exception",
            ):
                terminal, detail = ultimate._run_daily_route(
                    runtime=runtime,
                    session=session,
                    frames=frames,
                    events=events,
                    atlas_path=root / "atlas.json",
                    reset_identity="game-day-2026-08-17",
                    maximum_pans=4,
                    post_input_delay=0,
                    entry_observation=SimpleNamespace(),
                    starting_state="ultimate_challenge",
                )

        self.assertEqual(terminal, "blocked_fail_closed")
        self.assertEqual(
            detail["challenge_action_key"],
            "tap_challenge-1-r16-predicate-exception",
        )
        self.assertIn("latest retained post capture", detail["reason"])
        self.assertIn("semantic post evidence is unavailable", detail["reason"])
        self.assertEqual(
            detail["latest_capture_sha256"],
            runtime.captures[-1].sha256,
        )
        self.assertEqual(len(runtime.captures), 3)
        self.assertEqual(len(runtime.reconciliations), 1)
        key, status, post, reason = runtime.reconciliations[0]
        self.assertEqual(key, detail["challenge_action_key"])
        self.assertEqual(status, "unresolved")
        self.assertIs(post, runtime.captures[2])
        self.assertEqual(reason, detail["reason"])

    def test_route_reconciles_immediate_before_when_lineup_capture_raises(self) -> None:
        class CaptureFailsBeforePost(self._RouteRuntime):
            def capture(self, label: str) -> CapturedNativeFrame:
                if label.startswith("hero-lineup-successor"):
                    raise RuntimeError("synthetic post capture failure")
                return super().capture(label)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            session.mkdir()
            frames = session / "frames"
            frames.mkdir()
            events = session / "events.jsonl"
            runtime = CaptureFailsBeforePost(
                root,
                np.zeros((1280, 800, 3), dtype=np.uint8),
            )
            with patch.object(
                ultimate,
                "_recognize_ultimate_main",
                return_value=(320, 1195, 480, 1245),
            ), patch.object(
                ultimate.time,
                "sleep",
                return_value=None,
            ), patch.object(
                ultimate,
                "utc_stamp",
                return_value="r16-capture-exception",
            ):
                terminal, detail = ultimate._run_daily_route(
                    runtime=runtime,
                    session=session,
                    frames=frames,
                    events=events,
                    atlas_path=root / "atlas.json",
                    reset_identity="game-day-2026-08-17",
                    maximum_pans=4,
                    post_input_delay=0,
                    entry_observation=SimpleNamespace(),
                    starting_state="ultimate_challenge",
                )

        self.assertEqual(terminal, "blocked_fail_closed")
        self.assertEqual(
            detail["challenge_action_key"],
            "tap_challenge-1-r16-capture-exception",
        )
        self.assertIn("no post capture was retained", detail["reason"])
        self.assertIn("semantic post evidence is unavailable", detail["reason"])
        self.assertEqual(
            detail["latest_capture_sha256"],
            runtime.captures[-1].sha256,
        )
        self.assertEqual(len(runtime.captures), 2)
        self.assertEqual(len(runtime.reconciliations), 1)
        key, status, post, reason = runtime.reconciliations[0]
        self.assertEqual(key, detail["challenge_action_key"])
        self.assertEqual(status, "unresolved")
        self.assertIs(post, runtime.captures[1])
        self.assertEqual(reason, detail["reason"])


class UltimateVipResetContinuationTests(unittest.TestCase):
    POPUP_FRAME = ROOT / "tasks/assets/navigation/800x1280/reset_popup_source.png"
    LINEUP_ROI = (300, 1175, 500, 1230)

    class _Runtime:
        def __init__(
            self,
            root: Path,
            captures: list[CapturedNativeFrame],
            *,
            tap_error: BaseException | None = None,
            capture_error: BaseException | None = None,
            capture_error_after: int = 0,
        ) -> None:
            self.root = root
            self._captures = list(captures)
            self.tap_error = tap_error
            self.capture_error = capture_error
            self.capture_error_after = capture_error_after
            self.input_count = 0
            self.action_keys: set[str] = set()
            self.captures: list[CapturedNativeFrame] = []
            self.capture_labels: list[str] = []
            self.taps: list[dict[str, object]] = []
            self.reconciliations: list[
                tuple[str, str, CapturedNativeFrame, str]
            ] = []
            self.runner = SimpleNamespace()

        def capture(self, label: str) -> CapturedNativeFrame:
            self.capture_labels.append(label)
            if (
                self.capture_error is not None
                and len(self.captures) >= self.capture_error_after
            ):
                error = self.capture_error
                self.capture_error = None
                raise error
            captured = self._captures.pop(0)
            self.captures.append(captured)
            return captured

        def tap(self, source, **kwargs) -> None:
            self.taps.append({"source": source, **kwargs})
            if self.tap_error is not None:
                self.input_count += 1
                self.action_keys.add(str(kwargs["action_key"]))
                raise self.tap_error
            self.input_count += 1
            self.action_keys.add(str(kwargs["action_key"]))

        def reconcile(
            self,
            action_key: str,
            status: str,
            post: CapturedNativeFrame,
            reason: str,
        ) -> None:
            self.reconciliations.append((action_key, status, post, reason))

    @staticmethod
    def _lineup_frame() -> np.ndarray:
        return UltimateChallengeLineupTests._lineup_frame()

    @staticmethod
    def _captured(
        root: Path,
        frame: np.ndarray,
        label: str,
        ordinal: int,
    ) -> CapturedNativeFrame:
        return UltimateChallengeLineupTests._captured(root, frame, label, ordinal)

    @staticmethod
    def _lineup_ocr() -> dict[str, list[str]]:
        return {
            "text": ["Hero", "Lineup"],
            "conf": ["96", "96"],
        }

    def _initial_popup(self, root: Path) -> CapturedNativeFrame:
        frame = cv2.imread(str(self.POPUP_FRAME), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        return self._captured(root, frame, "campaign-resume-source", 1)

    def _run_continuation(
        self,
        root: Path,
        runtime: _Runtime,
        initial: CapturedNativeFrame,
        initial_observation: dict[str, object],
    ):
        with patch.object(
            ultimate.pytesseract,
            "image_to_data",
            return_value=self._lineup_ocr(),
        ), patch.object(ultimate.time, "sleep", return_value=None):
            return ultimate._continue_from_vip_reset_popup(
                runtime=runtime,
                initial=initial,
                initial_observation=initial_observation,
                session=root / "session",
                events=root / "session" / "events.jsonl",
                post_input_delay=0,
            )

    def test_real_shared_popup_and_lineup_success_use_one_exact_tap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            (session / "frames").mkdir(parents=True)
            (session / "events.jsonl").touch()
            initial = self._initial_popup(root)
            immediate = self._captured(
                root,
                initial.frame,
                "vip-reset-close-immediate-before",
                2,
            )
            settled = self._captured(
                root,
                self._lineup_frame(),
                "vip-reset-close-settled",
                3,
            )
            initial_observation = ultimate.recognize_reset_popup(initial.frame)
            self.assertTrue(initial_observation["recognized"])
            runtime = self._Runtime(root, [immediate, settled])
            resumed, settled_path, detail = self._run_continuation(
                root,
                runtime,
                initial,
                initial_observation,
            )

        self.assertIs(resumed, settled)
        self.assertEqual(settled_path, "frames/campaign-resume-source.png")
        self.assertEqual(detail["status"], "confirmed")
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(len(runtime.taps), 1)
        tap = runtime.taps[0]
        self.assertEqual(tap["target_identity"], "reset-popup-close")
        self.assertEqual(tap["target_roi"], tuple(initial_observation["target"]))
        self.assertEqual(
            tap["action_key"],
            f"reset-popup-close:{immediate.sha256}",
        )
        self.assertFalse(tap["consequential"])
        self.assertEqual(runtime.capture_labels, [
            "vip-reset-close-immediate-before",
            "vip-reset-close-settled",
        ])
        self.assertEqual(len(runtime.reconciliations), 1)
        key, status, post, _reason = runtime.reconciliations[0]
        self.assertEqual(key, tap["action_key"])
        self.assertEqual(status, "confirmed")
        self.assertIs(post, settled)
        self.assertEqual(detail["lineup_roi"], self.LINEUP_ROI)

    def test_wrong_popup_text_and_close_identity_are_rejected_by_shared_recognizer(self) -> None:
        frame = cv2.imread(str(self.POPUP_FRAME), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        variants = {
            "wrong_title": (260, 390, 540, 440),
            "wrong_body": (120, 480, 680, 720),
            "wrong_close": (260, 790, 540, 825),
        }
        for label, (x0, y0, x1, y1) in variants.items():
            with self.subTest(case=label):
                changed = frame.copy()
                changed[y0:y1, x0:x1] = 0
                observation = ultimate.recognize_reset_popup(changed)
                self.assertFalse(observation["recognized"])
                self.assertFalse(ultimate._exact_vip_reset_popup(observation))

    def test_moved_or_ambiguous_fresh_target_fails_before_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            (session / "frames").mkdir(parents=True)
            (session / "events.jsonl").touch()
            initial = self._initial_popup(root)
            initial_observation = ultimate.recognize_reset_popup(initial.frame)
            moved = initial.frame.copy()
            moved[781:869, 263:537] = 0
            moved[781:869, 270:540] = initial.frame[781:869, 263:533]
            immediate = self._captured(
                root,
                moved,
                "vip-reset-close-immediate-before",
                2,
            )
            runtime = self._Runtime(root, [immediate])
            _resumed, _path, detail = self._run_continuation(
                root,
                runtime,
                initial,
                initial_observation,
            )
            self.assertEqual(runtime.input_count, 0)
            self.assertEqual(runtime.taps, [])
            self.assertIn("drifted", detail["reason"])

            ambiguous_runtime = self._Runtime(
                root,
                [self._captured(root, initial.frame, "vip-reset-close-immediate-before", 3)],
            )
            with patch.object(
                ultimate,
                "recognize_reset_popup",
                return_value={
                    **initial_observation,
                    "target": None,
                    "recognized": False,
                },
            ):
                _resumed, _path, ambiguous_detail = self._run_continuation(
                    root,
                    ambiguous_runtime,
                    initial,
                    initial_observation,
                )
            self.assertEqual(ambiguous_runtime.input_count, 0)
            self.assertEqual(ambiguous_runtime.taps, [])
            self.assertIn("drifted", ambiguous_detail["reason"])

    def test_persistent_or_unknown_successor_reconciles_settled_unresolved_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            (session / "frames").mkdir(parents=True)
            (session / "events.jsonl").touch()
            initial = self._initial_popup(root)
            initial_observation = ultimate.recognize_reset_popup(initial.frame)
            immediate = self._captured(root, initial.frame, "immediate", 2)
            settled = self._captured(root, self._lineup_frame(), "settled", 3)
            for case, settled_popup, lineup_roi in (
                ("persistent", {"recognized": True}, self.LINEUP_ROI),
                ("unknown", {"recognized": False}, None),
            ):
                with self.subTest(case=case):
                    runtime = self._Runtime(root, [immediate, settled])
                    with patch.object(
                        ultimate,
                        "recognize_reset_popup",
                        side_effect=[initial_observation, settled_popup],
                    ), patch.object(
                        ultimate,
                        "_bind_lineup_challenge_button",
                        return_value=lineup_roi,
                    ), patch.object(
                        ultimate,
                        "_recognize_ultimate_main",
                        return_value=None,
                    ), patch.object(
                        ultimate,
                        "_recognize_active_battle",
                        return_value=None,
                    ), patch.object(
                        ultimate,
                        "_bind_flee_warning_button",
                        return_value=None,
                    ), patch.object(ultimate.time, "sleep", return_value=None):
                        _resumed, _path, detail = ultimate._continue_from_vip_reset_popup(
                            runtime=runtime,
                            initial=initial,
                            initial_observation=initial_observation,
                            session=session,
                            events=session / "events.jsonl",
                            post_input_delay=0,
                        )
                    self.assertEqual(runtime.input_count, 1)
                    self.assertEqual(len(runtime.taps), 1)
                    self.assertEqual(len(runtime.reconciliations), 1)
                    key, status, post, _reason = runtime.reconciliations[0]
                    self.assertEqual(status, "unresolved")
                    self.assertIs(post, settled)
                    self.assertEqual(key, runtime.taps[0]["action_key"])
                    self.assertIn("Hero Lineup", detail["reason"])
                    immediate = self._captured(root, initial.frame, "immediate", 4)
                    settled = self._captured(root, self._lineup_frame(), "settled", 5)

    def test_transport_and_capture_failures_reconcile_only_accounted_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            (session / "frames").mkdir(parents=True)
            (session / "events.jsonl").touch()
            initial = self._initial_popup(root)
            initial_observation = ultimate.recognize_reset_popup(initial.frame)

            accounted = self._Runtime(
                root,
                [self._captured(root, initial.frame, "immediate", 2)],
                tap_error=RuntimeError("transport"),
            )
            _resumed, _path, _detail = self._run_continuation(
                root,
                accounted,
                initial,
                initial_observation,
            )
            self.assertEqual(accounted.input_count, 1)
            self.assertEqual(len(accounted.reconciliations), 1)
            self.assertIs(accounted.reconciliations[0][2], accounted.captures[0])

            pre_dispatch = self._Runtime(
                root,
                [self._captured(root, initial.frame, "immediate", 3)],
                tap_error=RuntimeError("guard"),
            )
            pre_dispatch.tap = lambda _source, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("guard")
            )
            _resumed, _path, _detail = self._run_continuation(
                root,
                pre_dispatch,
                initial,
                initial_observation,
            )
            self.assertEqual(pre_dispatch.input_count, 0)
            self.assertEqual(pre_dispatch.reconciliations, [])

            capture_failure = self._Runtime(
                root,
                [self._captured(root, initial.frame, "immediate", 4)],
                capture_error=RuntimeError("capture"),
                capture_error_after=1,
            )
            _resumed, _path, _detail = self._run_continuation(
                root,
                capture_failure,
                initial,
                initial_observation,
            )
            self.assertEqual(capture_failure.input_count, 1)
            self.assertEqual(len(capture_failure.reconciliations), 1)
            self.assertIs(
                capture_failure.reconciliations[0][2],
                capture_failure.captures[0],
            )
            self.assertEqual(len(capture_failure.taps), 1)

    def test_daily_route_uses_settled_lineup_without_recapture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            session.mkdir()
            frames = session / "frames"
            frames.mkdir()
            events = session / "events.jsonl"
            lineup = self._captured(root, self._lineup_frame(), "settled", 1)
            runtime = self._Runtime(root, [])
            active = self._captured(root, np.zeros((1280, 800, 3), dtype=np.uint8), "active", 2)
            warning = self._captured(root, np.zeros((1280, 800, 3), dtype=np.uint8), "warning", 3)
            fled = self._captured(root, np.zeros((1280, 800, 3), dtype=np.uint8), "fled", 4)
            with patch.object(
                ultimate,
                "_capture_until",
                side_effect=[active, warning, fled],
            ), patch.object(
                ultimate,
                "_recognize_active_battle",
                return_value=(700, 20, 750, 75),
            ), patch.object(
                ultimate,
                "_bind_flee_warning_button",
                return_value=(470, 600, 700, 700),
            ), patch.object(
                ultimate,
                "_recognize_ultimate_main",
                return_value=(320, 1195, 480, 1245),
            ), patch.object(
                ultimate,
                "_run_post_flee_home_route",
                return_value=("complete_for_reset", {"reason": "test"}),
            ), patch.object(ultimate, "utc_stamp", return_value="r17-test"):
                terminal, _detail = ultimate._run_daily_route(
                    runtime=runtime,
                    session=session,
                    frames=frames,
                    events=events,
                    atlas_path=root / "atlas.json",
                    reset_identity="game-day-2026-08-17",
                    maximum_pans=4,
                    post_input_delay=0,
                    entry_observation=SimpleNamespace(),
                    starting_state="hero_lineup",
                    resume_capture=lineup,
                    resume_lineup_roi=self.LINEUP_ROI,
                )
        self.assertEqual(terminal, "complete_for_reset")
        self.assertEqual(runtime.capture_labels, [])
        self.assertIs(runtime.taps[0]["source"], lineup)

    def test_main_passes_settled_vip_successor_to_daily_route(self) -> None:
        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [
                    type(
                        "Device",
                        (),
                        {"serial": "emulator-5554", "state": "device"},
                    )()
                ]

            def get_state(self) -> str:
                return "device"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            popup = cv2.imread(str(self.POPUP_FRAME), cv2.IMREAD_COLOR)
            self.assertIsNotNone(popup)
            initial = self._captured(root, popup, "initial", 1)
            immediate = self._captured(root, popup, "immediate", 2)
            settled = self._captured(
                root,
                self._lineup_frame(),
                "settled",
                3,
            )
            runtime_instances: list[UltimateVipResetContinuationTests._Runtime] = []

            def fake_runtime(_runner, runtime_session: Path, *, execute: bool):
                runtime = self._Runtime(root, [initial, immediate, settled])
                runtime.session = runtime_session
                runtime_instances.append(runtime)
                self.assertTrue(execute)
                return runtime

            daily_calls: list[dict[str, object]] = []

            def fake_daily(**kwargs):
                daily_calls.append(kwargs)
                return "blocked_fail_closed", {
                    "reason": "test route stop",
                    "completed_actions": [],
                }

            def fake_entry(frame, *, reset_identity):
                return SimpleNamespace(
                    campaign_screen_recognized=False,
                    entry_control_visible=False,
                    entry_control_identity="",
                    entry_roi=None,
                    already_completed_marker=False,
                    reset_identity=reset_identity,
                    source_frame_sha256=ultimate.frame_sha256(frame),
                )

            output = root / "output"
            with patch.object(ultimate, "ADBRunner", FakeRunner), patch.object(
                ultimate,
                "LocalBlueStacksRuntime",
                side_effect=fake_runtime,
            ), patch.object(
                ultimate,
                "is_permitted_local_bluestacks_serial",
                return_value=True,
            ), patch.object(
                ultimate,
                "require_campaign_home_atlas_building",
            ), patch.object(
                ultimate,
                "_bind_ultimate_challenge_entry",
                side_effect=fake_entry,
            ), patch.object(
                ultimate,
                "_run_daily_route",
                side_effect=fake_daily,
            ), patch.object(
                ultimate.pytesseract,
                "image_to_data",
                return_value=self._lineup_ocr(),
            ), patch.object(
                ultimate.time,
                "sleep",
                return_value=None,
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

        self.assertEqual(code, 3)
        self.assertEqual(len(runtime_instances), 1)
        self.assertEqual(len(daily_calls), 1)
        runtime = runtime_instances[0]
        self.assertIs(daily_calls[0]["runtime"], runtime)
        self.assertEqual(daily_calls[0]["starting_state"], "hero_lineup")
        self.assertIs(daily_calls[0]["resume_capture"], settled)
        self.assertEqual(daily_calls[0]["resume_lineup_roi"], self.LINEUP_ROI)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(len(runtime.taps), 1)


class UltimateHomeNormalizationTests(unittest.TestCase):
    @staticmethod
    def _home_frame(*, marker: int = 0) -> np.ndarray:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        template = cv2.imread(
            str(ROOT / "tasks/assets/home_nav/800x1280/home_nav_strip.png"),
            cv2.IMREAD_COLOR,
        )
        frame[1213:1280] = template
        if marker:
            frame[300, 300] = (marker, marker, marker)
        return frame

    @staticmethod
    def _non_home_frame() -> np.ndarray:
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
        return frame

    @staticmethod
    def _atlas() -> HomeAtlas:
        return HomeAtlas(
            3,
            "ultimate-normalization-test",
            "1",
            PlatformProfile(
                BLUESTACKS_PLATFORM,
                BLUESTACKS_PROFILE_ID,
                (800, 1280),
                "com.global.ztmslg",
            ),
            "fully_zoomed_out",
            "atlas pixels",
            (0, 0),
            800,
            1280,
            "atlas.png",
            "test",
            "test",
            (
                (
                    (0, 0),
                    (800, 0),
                    (800, 1280),
                    (0, 1280),
                ),
            ),
            (),
            (
                AtlasViewport(
                    "viewport-001",
                    "unused.png",
                    "a" * 64,
                    "now",
                    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
                    ((0, 0), (800, 0), (800, 1280), (0, 1280)),
                    1,
                    0,
                    "translation",
                ),
            ),
            (
                SemanticBuilding(
                    "home.building.campaign",
                    "Campaign",
                    ((300, 400), (440, 400), (440, 540), (300, 540)),
                    0.98,
                    ("test",),
                    recognition={"bluestacks": {"label": "Campaign"}},
                    semantic_proof=("test Campaign label",),
                    interaction_eligible=True,
                    platform_binding_policy={"bluestacks": {"label": "Campaign"}},
                ),
            ),
            (
                (
                    (0, 0),
                    (800, 0),
                    (800, 1280),
                    (0, 1280),
                ),
            ),
            (0.0, 0.0, 800.0, 1280.0),
        )

    class _Localizer:
        def __init__(self, initial: np.ndarray, canonical: np.ndarray, *, unknown: bool = False):
            self.initial = initial
            self.canonical_reference = canonical
            self.unknown = unknown

        def localize(self, frame: np.ndarray) -> LocalizationResult:
            digest = frame_digest(frame)
            if self.unknown:
                return LocalizationResult(
                    False,
                    BLUESTACKS_PLATFORM,
                    BLUESTACKS_PROFILE_ID,
                    ZoomIdentity.UNKNOWN,
                    None,
                    (),
                    0.0,
                    (),
                    None,
                    AmbiguityState.INSUFFICIENT_LANDMARKS,
                    "unknown",
                    digest,
                    "now",
                )
            if np.array_equal(frame, self.canonical_reference):
                return LocalizationResult(
                    True,
                    BLUESTACKS_PLATFORM,
                    BLUESTACKS_PROFILE_ID,
                    ZoomIdentity.FULLY_ZOOMED_OUT,
                    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
                    ((0, 0), (800, 0), (800, 1280), (0, 1280)),
                    0.95,
                    ("landmark-1",),
                    0.0,
                    AmbiguityState.NONE,
                    "interior",
                    digest,
                    "now",
                )
            return LocalizationResult(
                False,
                BLUESTACKS_PLATFORM,
                BLUESTACKS_PROFILE_ID,
                ZoomIdentity.ZOOMED_IN,
                None,
                (),
                0.92,
                ("landmark-1",),
                0.1,
                AmbiguityState.NONE,
                "interior",
                digest,
                "now",
            )

    class _Runtime:
        execute = True
        max_inputs = ultimate.MAX_TOTAL_INPUTS

        def __init__(
            self,
            root: Path,
            initial: np.ndarray,
            factory,
            *,
            input_count: int = 0,
            immediate_before_frame: np.ndarray | None = None,
        ):
            self.session = root / "runtime"
            self.session.mkdir(parents=True)
            self.current = initial
            self.factory = factory
            self.immediate_before_frame = immediate_before_frame
            self.input_count = input_count
            self.capture_count = 0
            self.captures_by_label: dict[str, CapturedNativeFrame] = {}
            self.zoom_dispatches: list[str] = []
            self.action_keys: set[str] = set()
            self.dispatched_external_zoom_key: str | None = None
            self.reconciliations: list[tuple[str, str]] = []
            self.reconciliation_attempts: list[tuple[str, str]] = []
            self.reconciliation_posts: list[CapturedNativeFrame] = []
            self.reconciliation_errors: list[str] = []
            self.runner = SimpleNamespace()

        def _captured(self, label: str) -> CapturedNativeFrame:
            self.capture_count += 1
            ok, encoded = cv2.imencode(".png", self.current)
            assert ok
            payload = encoded.tobytes()
            path = self.session / f"{self.capture_count:04d}-{label}.png"
            path.write_bytes(payload)
            captured = CapturedNativeFrame(
                self.current.copy(),
                payload,
                hashlib.sha256(payload).hexdigest(),
                time.monotonic(),
                path,
            )
            self.captures_by_label[label] = captured
            return captured

        def capture(self, label: str) -> CapturedNativeFrame:
            if (
                label.endswith("-immediate-before")
                and self.immediate_before_frame is not None
            ):
                self.current = self.immediate_before_frame.copy()
            return self._captured(label)

        def measure_foreground_package(self) -> str:
            return "com.global.ztmslg"

        def measure_device_state(self) -> str:
            return "device"

        def dispatch_external_zoom(self, source, *, action_key: str, transport) -> None:
            if self.input_count >= self.max_inputs:
                raise RuntimeError("development session input limit reached")
            self.input_count += 1
            self.action_keys.add(action_key)
            self.zoom_dispatches.append(action_key)
            self.dispatched_external_zoom_key = action_key
            transport()
            self.current = self.factory(self.input_count)

        def reconcile(self, action_key: str, status: str, post, reason: str) -> None:
            self.reconciliation_attempts.append((action_key, status))
            if action_key != self.dispatched_external_zoom_key:
                self.reconciliation_errors.append(action_key)
                raise AssertionError(
                    "reconciliation key does not match dispatched external-zoom key"
                )
            self.reconciliation_posts.append(post)
            self.reconciliations.append((action_key, status))

    class _Transport:
        instances: list["UltimateHomeNormalizationTests._Transport"] = []
        fail = False

        def __init__(self, **_kwargs):
            self.calls = 0
            self.instances.append(self)

        def zoom_out_once(self) -> None:
            self.calls += 1
            if self.fail:
                raise RuntimeError("synthetic zoom transport failure")

    class _RefreshDispositionDriver:
        def __init__(self, refreshed_disposition: ultimate.HomeDriverDisposition):
            self.refreshed_disposition = refreshed_disposition
            self.observed_digests: list[str] = []
            self.zoom_inputs = 0

        def observe(self, frame: np.ndarray):
            digest = ultimate.frame_sha256(frame)
            self.observed_digests.append(digest)
            disposition = (
                ultimate.HomeDriverDisposition.RECOVER_ZOOM
                if len(self.observed_digests) == 1
                else self.refreshed_disposition
            )
            return SimpleNamespace(
                disposition=disposition,
                reason=(
                    "unsupported_zoom_requires_bounded_canonical_recovery"
                    if disposition is ultimate.HomeDriverDisposition.RECOVER_ZOOM
                    else "synthetic refreshed disposition"
                ),
                source_frame_sha256=digest,
                localization=SimpleNamespace(
                    zoom_identity=ZoomIdentity.ZOOMED_IN,
                    recognized=True,
                    confidence=0.92,
                    residual_px=0.1,
                    overlay=False,
                    stale=False,
                    ambiguity_state=AmbiguityState.NONE,
                ),
            )

        def record_zoom_input_dispatched(self, _source_frame_sha256: str) -> None:
            raise AssertionError("refreshed non-recovery step must not dispatch")

    class _SettledDispositionDriver:
        def __init__(
            self,
            disposition: ultimate.HomeDriverDisposition,
            *,
            safe_terminal: bool = True,
        ):
            self.disposition = disposition
            self.safe_terminal = safe_terminal
            self.observed_digests: list[str] = []
            self.zoom_inputs = 0
            self.pan_dispatches: list[object] = []

        def observe(self, frame: np.ndarray):
            digest = ultimate.frame_sha256(frame)
            self.observed_digests.append(digest)
            terminal = len(self.observed_digests) >= 3
            localization = SimpleNamespace(
                zoom_identity=(
                    ZoomIdentity.FULLY_ZOOMED_OUT
                    if terminal and self.safe_terminal
                    else ZoomIdentity.ZOOMED_IN
                ),
                recognized=terminal and self.safe_terminal,
                confidence=0.987377 if terminal and self.safe_terminal else 0.92,
                residual_px=0.1,
                overlay=not self.safe_terminal and terminal,
                stale=False,
                ambiguity_state=(
                    AmbiguityState.NONE
                    if terminal and self.safe_terminal
                    else AmbiguityState.INSUFFICIENT_LANDMARKS
                ),
                screen_to_atlas=(
                    ((1, 0, 0), (0, 1, 0), (0, 0, 1))
                    if terminal and self.safe_terminal
                    else None
                ),
            )
            return SimpleNamespace(
                disposition=(
                    self.disposition
                    if terminal
                    else ultimate.HomeDriverDisposition.RECOVER_ZOOM
                ),
                reason=(
                    "synthetic settled terminal"
                    if terminal
                    else "synthetic zoom recovery"
                ),
                source_frame_sha256=digest,
                localization=localization,
            )

        def record_zoom_input_dispatched(self, _source_frame_sha256: str) -> None:
            self.zoom_inputs += 1

    def _run_normalizer(
        self,
        *,
        factory,
        unknown: bool = False,
        input_count: int = 0,
        overlay: bool = False,
        transport_failure: bool = False,
        initial_canonical: bool = False,
        guard_denial: bool = False,
        driver_accounting_failure: bool = False,
        immediate_before_frame: np.ndarray | None = None,
        driver=None,
    ):
        root = Path(tempfile.mkdtemp())
        initial = self._home_frame(marker=0 if initial_canonical else 1)
        canonical = self._home_frame()
        runtime = self._Runtime(
            root,
            initial,
            factory,
            input_count=input_count,
            immediate_before_frame=immediate_before_frame,
        )
        source = runtime._captured("source")
        localizer = self._Localizer(initial, canonical, unknown=unknown)
        self._Transport.instances = []
        self._Transport.fail = transport_failure
        def fake_zoom_classification(frame, _canonical_reference):
            marker = int(frame[300, 300, 0])
            return SimpleNamespace(
                scale=0.70 + min(marker, ultimate.MAX_HOME_ZOOM_INPUTS) * 0.02,
                identity=ZoomIdentity.ZOOMED_IN,
            )
        driver_patch = patch.object(
            ultimate,
            "BlueStacksLocalizeFirstHomeDriver",
            return_value=driver,
        ) if driver is not None else nullcontext()
        with patch.object(ultimate, "load_home_atlas", return_value=self._atlas()), patch.object(
            ultimate, "BlueStacksHomeLocalizer", return_value=localizer
        ), patch.object(
            ultimate, "ScrcpyMotionEventZoomTransport", self._Transport
        ), patch.object(
            ultimate, "classify_zoom", side_effect=fake_zoom_classification
        ), driver_patch:
            popup_patch = patch.object(ultimate, "_unexpected_visual_popup", return_value=True) if overlay else patch.object(
                ultimate, "_unexpected_visual_popup", wraps=ultimate._unexpected_visual_popup
            )
            with popup_patch:
                def run_normalizer():
                    return ultimate._normalize_ultimate_home_before_campaign(
                        runtime=runtime,
                        session=root,
                        events=root / "events.jsonl",
                        atlas_path=root / "atlas.json",
                        adb=Path("fake-adb"),
                        serial="emulator-5554",
                        source=source,
                        maximum_pans=4,
                        post_input_delay=0,
                    )

                if guard_denial:
                    with patch.object(
                        ultimate.NavigationGuardedRuntime,
                        "dispatch_zoom_out",
                        side_effect=RuntimeError("synthetic guard denial"),
                    ):
                        ok, detail = run_normalizer()
                elif driver_accounting_failure:
                    with patch.object(
                        ultimate.BlueStacksLocalizeFirstHomeDriver,
                        "record_zoom_input_dispatched",
                        side_effect=RuntimeError("synthetic driver accounting failure"),
                    ):
                        ok, detail = run_normalizer()
                else:
                    ok, detail = run_normalizer()
        return root, runtime, ok, detail

    def test_already_canonical_home_uses_zero_zoom(self) -> None:
        canonical = self._home_frame()
        _root, runtime, ok, detail = self._run_normalizer(
            factory=lambda _count: canonical,
            initial_canonical=True,
        )
        self.assertTrue(ok)
        self.assertEqual(detail["zoom_input_count"], 0)
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(runtime.zoom_dispatches, [])

    def test_main_hands_off_after_settled_pan_normalization(self) -> None:
        initial = self._home_frame(marker=1)
        canonical = self._home_frame()
        runtime_instances: list[UltimateHomeNormalizationTests._Runtime] = []
        driver = self._SettledDispositionDriver(
            ultimate.HomeDriverDisposition.PAN,
        )
        safe_downstream = UltimateChallengeEntryObservation(
            campaign_screen_recognized=False,
            entry_control_visible=False,
            entry_control_identity="",
            entry_roi=None,
            already_completed_marker=False,
            reset_identity="game-day-2026-08-17",
            source_frame_sha256=ultimate.frame_sha256(initial),
        )

        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [
                    type(
                        "Device",
                        (),
                        {"serial": "emulator-5554", "state": "device"},
                    )()
                ]

            def get_state(self) -> str:
                return "device"

        def fake_runtime(_runner, session: Path, *, execute: bool):
            runtime = self._Runtime(
                session.parent,
                initial,
                lambda _count: canonical,
            )
            self.assertTrue(execute)
            runtime_instances.append(runtime)
            return runtime

        def fake_zoom_classification(frame, _canonical_reference):
            marker = int(frame[300, 300, 0])
            return SimpleNamespace(
                scale=0.70 + min(marker, ultimate.MAX_HOME_ZOOM_INPUTS) * 0.02,
                identity=ZoomIdentity.ZOOMED_IN,
            )

        def fake_campaign(runtime, **kwargs):
            self.assertEqual(len(runtime.zoom_dispatches), 1)
            self.assertEqual(
                runtime.reconciliations,
                [(runtime.dispatched_external_zoom_key, "confirmed")],
            )
            self.assertIs(
                runtime.reconciliation_posts[0],
                runtime.captures_by_label["ultimate-home-zoom-01-settled"],
            )
            self.assertEqual(driver.pan_dispatches, [])
            self.assertEqual(kwargs["maximum_pans"], 4)
            self.assertTrue(kwargs["execute"])
            return {"status": "opened", "records": []}

        self._Transport.instances = []
        self._Transport.fail = False
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(ultimate, "ADBRunner", FakeRunner), patch.object(
                ultimate, "LocalBlueStacksRuntime", side_effect=fake_runtime
            ), patch.object(
                ultimate, "is_permitted_local_bluestacks_serial", return_value=True
            ), patch.object(
                ultimate, "require_campaign_home_atlas_building"
            ), patch.object(
                ultimate, "load_home_atlas", return_value=self._atlas()
            ), patch.object(
                ultimate,
                "BlueStacksHomeLocalizer",
                return_value=self._Localizer(initial, canonical),
            ), patch.object(
                ultimate, "ScrcpyMotionEventZoomTransport", self._Transport
            ), patch.object(
                ultimate, "classify_zoom", side_effect=fake_zoom_classification
            ), patch.object(
                ultimate,
                "BlueStacksLocalizeFirstHomeDriver",
                return_value=driver,
            ), patch.object(
                ultimate,
                "_bind_ultimate_challenge_entry",
                return_value=safe_downstream,
            ), patch.object(
                ultimate,
                "run_verified_ultimate_challenge_campaign_door",
                side_effect=fake_campaign,
            ) as campaign:
                code = ultimate.main(
                    [
                        "--adb",
                        "unused-adb",
                        "--serial",
                        "emulator-5554",
                        "--navigation-only",
                        "--execute",
                        "--yes",
                        "--atlas",
                        str(output / "atlas.json"),
                        "--maximum-pans",
                        "4",
                        "--post-input-delay",
                        "0",
                        "--output-directory",
                        str(output),
                        "--reset-identity",
                        "game-day-2026-08-17",
                    ]
                )

            sessions = list(output.glob("nav-*"))
            self.assertEqual(code, 3)
            self.assertEqual(len(sessions), 1)
            result = json.loads((sessions[0] / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(campaign.call_count, 1)
        self.assertEqual(len(runtime_instances), 1)
        runtime = runtime_instances[0]
        self.assertIs(campaign.call_args.args[0], runtime)
        self.assertEqual(campaign.call_args.kwargs["maximum_pans"], 4)
        self.assertTrue(campaign.call_args.kwargs["execute"])
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(len(runtime.zoom_dispatches), 1)
        action_key = runtime.zoom_dispatches[0]
        self.assertEqual(
            runtime.reconciliations,
            [(action_key, "confirmed")],
        )
        self.assertEqual(action_key, runtime.dispatched_external_zoom_key)
        self.assertIs(
            runtime.reconciliation_posts[0],
            runtime.captures_by_label["ultimate-home-zoom-01-settled"],
        )
        self.assertEqual(driver.pan_dispatches, [])
        self.assertEqual(result["home_normalization"]["status"], "completed")
        self.assertEqual(result["home_normalization"]["zoom_input_count"], 1)
        self.assertEqual(result["home_normalization"]["terminal_zoom_identity"], "fully_zoomed_out")

    def test_edge_spanning_scenery_does_not_block_synthetic_home_normalization(self) -> None:
        canonical = self._home_frame()
        edge_spanning_scenery = (34, 588, 799, 1091)
        with patch.object(
            ultimate,
            "_visual_popup_panel_candidates",
            return_value=[edge_spanning_scenery],
        ):
            root, runtime, ok, detail = self._run_normalizer(
                factory=lambda _count: canonical,
                initial_canonical=True,
            )
        self.assertTrue(ok)
        self.assertEqual(detail["zoom_input_count"], 0)
        self.assertEqual(runtime.input_count, 0)

    def test_recoverable_zoom_uses_guarded_counted_transport(self) -> None:
        canonical = self._home_frame()
        root, runtime, ok, detail = self._run_normalizer(
            factory=lambda _count: canonical,
        )
        self.assertTrue(ok)
        self.assertEqual(detail["zoom_input_count"], 1)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(len(runtime.zoom_dispatches), 1)
        self.assertEqual(runtime.reconciliations[0][1], "confirmed")
        self.assertEqual(
            runtime.reconciliations[0][0],
            runtime.dispatched_external_zoom_key,
        )
        self.assertEqual(self._Transport.instances[0].calls, 1)
        action_keys = [
            record["action_key"]
            for record in detail["records"]
            if "action_key" in record
        ]
        self.assertEqual(len(action_keys), len(set(action_keys)))

    def test_dynamic_immediate_before_replans_and_binds_all_accounting_to_it(self) -> None:
        immediate_frame = self._home_frame(marker=2)
        accounting_sources: list[str] = []
        original_record = (
            ultimate.BlueStacksLocalizeFirstHomeDriver.record_zoom_input_dispatched
        )

        def record_zoom_input(driver, source_frame_sha256: str) -> None:
            accounting_sources.append(source_frame_sha256)
            original_record(driver, source_frame_sha256)

        with patch.object(
            ultimate.BlueStacksLocalizeFirstHomeDriver,
            "record_zoom_input_dispatched",
            autospec=True,
            side_effect=record_zoom_input,
        ):
            _root, runtime, ok, detail = self._run_normalizer(
                factory=lambda _count: self._home_frame(),
                immediate_before_frame=immediate_frame,
            )

        self.assertTrue(ok)
        source = runtime.captures_by_label["source"]
        immediate_before = runtime.captures_by_label[
            "ultimate-home-zoom-01-immediate-before"
        ]
        immediate_semantic = ultimate.frame_sha256(immediate_before.frame)
        self.assertNotEqual(ultimate.frame_sha256(source.frame), immediate_semantic)
        self.assertEqual(accounting_sources, [immediate_semantic])
        action_key = f"home-zoom-out:{immediate_before.sha256}"
        self.assertEqual(runtime.zoom_dispatches, [action_key])
        self.assertEqual(runtime.reconciliations, [(action_key, "confirmed")])
        plan = next(record for record in detail["records"] if "action_key" in record)
        self.assertEqual(plan["action_key"], action_key)
        self.assertEqual(plan["source_frame_sha256"], immediate_semantic)
        self.assertEqual(plan["runtime_source_sha256"], immediate_before.sha256)
        self.assertEqual(plan["refreshed_source_frame_sha256"], immediate_semantic)
        self.assertNotEqual(plan["planned_source_frame_sha256"], immediate_semantic)

    def test_settled_fully_out_pan_ignores_transient_immediate_popup(self) -> None:
        driver = self._SettledDispositionDriver(
            ultimate.HomeDriverDisposition.PAN,
        )
        popup_calls: list[int] = []

        def transient_popup(_frame: np.ndarray) -> bool:
            popup_calls.append(len(popup_calls) + 1)
            return len(popup_calls) == 3

        with patch.object(
            ultimate,
            "_unexpected_visual_popup",
            side_effect=transient_popup,
        ):
            _root, runtime, ok, detail = self._run_normalizer(
                factory=lambda _count: self._home_frame(),
                driver=driver,
            )

        self.assertTrue(ok)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(len(runtime.zoom_dispatches), 1)
        action_key = runtime.dispatched_external_zoom_key
        self.assertIsNotNone(action_key)
        self.assertEqual(runtime.reconciliations, [(action_key, "confirmed")])
        self.assertEqual(runtime.reconciliation_attempts, [(action_key, "confirmed")])
        self.assertEqual(len(runtime.reconciliation_posts), 1)
        self.assertIs(
            runtime.reconciliation_posts[0],
            runtime.captures_by_label["ultimate-home-zoom-01-settled"],
        )
        self.assertEqual(driver.pan_dispatches, [])
        plan = next(record for record in detail["records"] if "action_key" in record)
        self.assertFalse(plan["immediate_post_home_recognized"])
        self.assertTrue(plan["settled_home_recognized"])
        self.assertEqual(plan["status"], "confirmed")
        self.assertNotIn("unresolved", {status for _, status in runtime.reconciliations})

    def test_settled_unsafe_terminal_does_not_confirm_or_recover_again(self) -> None:
        driver = self._SettledDispositionDriver(
            ultimate.HomeDriverDisposition.PAN,
            safe_terminal=False,
        )
        _root, runtime, ok, detail = self._run_normalizer(
            factory=lambda _count: self._home_frame(),
            driver=driver,
        )

        self.assertFalse(ok)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(len(runtime.zoom_dispatches), 1)
        self.assertEqual(
            runtime.reconciliations,
            [(runtime.dispatched_external_zoom_key, "unresolved")],
        )
        self.assertEqual(runtime.reconciliation_attempts, runtime.reconciliations)
        self.assertEqual(detail["zoom_input_count"], 1)
        self.assertNotIn("confirmed", {status for _, status in runtime.reconciliations})

    def test_popup_or_non_home_immediate_before_blocks_without_input(self) -> None:
        popup_frame = self._home_frame(marker=2)
        non_home_frame = self._non_home_frame()

        def popup_candidates(frame: np.ndarray):
            if int(frame[300, 300, 0]) == 2:
                return [(50, 400, 750, 800)]
            return []

        with patch.object(
            ultimate,
            "_central_popup_candidates",
            side_effect=popup_candidates,
        ):
            for label, immediate_before in (
                ("popup", popup_frame),
                ("non_home", non_home_frame),
            ):
                with self.subTest(case=label):
                    _root, runtime, ok, detail = self._run_normalizer(
                        factory=lambda _count: self._home_frame(),
                        immediate_before_frame=immediate_before,
                    )
                    self.assertFalse(ok)
                    self.assertEqual(runtime.input_count, 0)
                    self.assertEqual(runtime.zoom_dispatches, [])
                    self.assertEqual(runtime.reconciliation_attempts, [])
                    self.assertIn("immediate-before", str(detail["reason"]))

    def test_refreshed_unknown_or_changed_disposition_blocks_without_input(self) -> None:
        for disposition in (
            ultimate.HomeDriverDisposition.BLOCKED,
            ultimate.HomeDriverDisposition.PAN,
        ):
            with self.subTest(disposition=disposition.value):
                driver = self._RefreshDispositionDriver(disposition)
                _root, runtime, ok, detail = self._run_normalizer(
                    factory=lambda _count: self._home_frame(),
                    driver=driver,
                )
                self.assertFalse(ok)
                self.assertEqual(len(driver.observed_digests), 2)
                self.assertEqual(runtime.input_count, 0)
                self.assertEqual(runtime.zoom_dispatches, [])
                self.assertEqual(runtime.reconciliation_attempts, [])
                self.assertEqual(
                    detail["reason"],
                    "Home zoom immediate-before disposition changed: "
                    f"{disposition.value}",
                )

    def test_zoom_reconciliation_joins_exact_dispatched_key_on_success_and_failure(self) -> None:
        canonical = self._home_frame()
        _root, success_runtime, ok, _detail = self._run_normalizer(
            factory=lambda _count: canonical,
        )
        self.assertTrue(ok)
        self.assertEqual(
            success_runtime.reconciliations,
            [(success_runtime.dispatched_external_zoom_key, "confirmed")],
        )
        success_plan = [
            record for record in _detail["records"] if "action_key" in record
        ]
        self.assertEqual(
            success_plan[0]["action_key"],
            success_runtime.dispatched_external_zoom_key,
        )

        _root, failure_runtime, ok, detail = self._run_normalizer(
            factory=lambda _count: self._home_frame(marker=1),
            transport_failure=True,
        )
        self.assertFalse(ok)
        self.assertEqual(failure_runtime.input_count, 1)
        self.assertEqual(
            failure_runtime.action_keys,
            {failure_runtime.dispatched_external_zoom_key},
        )
        self.assertEqual(
            failure_runtime.reconciliation_attempts,
            [(failure_runtime.dispatched_external_zoom_key, "unresolved")],
        )
        self.assertEqual(
            failure_runtime.reconciliations,
            [(failure_runtime.dispatched_external_zoom_key, "unresolved")],
        )
        self.assertEqual(failure_runtime.reconciliation_errors, [])
        failure_plan = [
            record for record in detail["records"] if "action_key" in record
        ]
        self.assertEqual(
            failure_plan[0]["action_key"],
            failure_runtime.dispatched_external_zoom_key,
        )
        self.assertTrue(
            all(
                "reconciliation_error" not in record
                for record in detail["records"]
                if "action_key" in record
            )
        )

    def test_guard_denial_before_inner_dispatch_does_not_reconcile_unreserved_key(self) -> None:
        _root, runtime, ok, detail = self._run_normalizer(
            factory=lambda _count: self._home_frame(marker=1),
            guard_denial=True,
        )
        self.assertFalse(ok)
        self.assertEqual(runtime.input_count, 0)
        self.assertEqual(runtime.action_keys, set())
        self.assertEqual(runtime.zoom_dispatches, [])
        self.assertEqual(runtime.reconciliation_attempts, [])
        self.assertEqual(runtime.reconciliation_errors, [])
        plan = [record for record in detail["records"] if "action_key" in record]
        self.assertEqual(len(plan), 1)
        self.assertFalse(plan[0]["runtime_accounted"])
        self.assertEqual(detail["zoom_input_count"], 0)

    def test_driver_accounting_failure_reconciles_exact_runtime_key_unresolved(self) -> None:
        _root, runtime, ok, detail = self._run_normalizer(
            factory=lambda _count: self._home_frame(),
            driver_accounting_failure=True,
        )
        self.assertFalse(ok)
        self.assertEqual(runtime.input_count, 1)
        self.assertEqual(runtime.action_keys, {runtime.dispatched_external_zoom_key})
        self.assertEqual(
            runtime.reconciliation_attempts,
            [(runtime.dispatched_external_zoom_key, "unresolved")],
        )
        self.assertEqual(runtime.reconciliations, runtime.reconciliation_attempts)
        self.assertEqual(runtime.reconciliation_errors, [])
        self.assertEqual(len(runtime.reconciliation_posts), 1)
        self.assertIs(
            runtime.reconciliation_posts[0],
            runtime.captures_by_label["ultimate-home-zoom-01-settled"],
        )
        self.assertIsNot(
            runtime.reconciliation_posts[0],
            runtime.captures_by_label["ultimate-home-zoom-01-immediate-post"],
        )
        plan = [record for record in detail["records"] if "action_key" in record]
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0]["runtime_accounted"])
        self.assertEqual(plan[0]["status"], "unresolved")
        self.assertEqual(detail["zoom_input_count"], 1)

    def test_no_progress_home_successor_is_failed_confirmed_after_reobservation(self) -> None:
        _root, runtime, ok, detail = self._run_normalizer(
            factory=lambda _count: self._home_frame(marker=1),
        )
        self.assertFalse(ok)
        self.assertEqual(
            runtime.reconciliations,
            [(runtime.dispatched_external_zoom_key, "failed_confirmed")],
        )
        self.assertEqual(detail["reason"], "repeated_zoom_recovery_frame")
        plan_records = [
            record for record in detail["records"] if "action_key" in record
        ]
        self.assertEqual(len(plan_records), 1)
        self.assertEqual(plan_records[0]["status"], "failed_confirmed")

    def test_wrong_unknown_overlay_repeated_and_transport_failure_block(self) -> None:
        canonical = self._home_frame()
        cases = (
            ("wrong_or_unknown", dict(factory=lambda _count: canonical, unknown=True), 0),
            ("overlay", dict(factory=lambda _count: canonical, overlay=True), 0),
            (
                "repeated",
                dict(factory=lambda _count: self._home_frame(marker=1)),
                1,
            ),
            (
                "wrong_screen_successor",
                dict(factory=lambda _count: np.zeros((1280, 800, 3), dtype=np.uint8)),
                1,
            ),
            (
                "transport",
                dict(factory=lambda _count: self._home_frame(marker=1), transport_failure=True),
                1,
            ),
        )
        for label, kwargs, expected_inputs in cases:
            with self.subTest(case=label):
                _root, runtime, ok, detail = self._run_normalizer(**kwargs)
                self.assertFalse(ok)
                self.assertEqual(runtime.input_count, expected_inputs)
                self.assertTrue(detail["reason"])
                self.assertLessEqual(detail["zoom_input_count"], ultimate.MAX_HOME_ZOOM_INPUTS)

    def test_exhaustion_and_aggregate_ceiling_are_fail_closed(self) -> None:
        def changing_zoom(count: int) -> np.ndarray:
            return self._home_frame(marker=(count % 200) + 1)

        _root, runtime, ok, detail = self._run_normalizer(factory=changing_zoom)
        self.assertFalse(ok)
        self.assertEqual(runtime.input_count, ultimate.MAX_HOME_ZOOM_INPUTS)
        self.assertLessEqual(detail["zoom_input_count"], ultimate.MAX_HOME_ZOOM_INPUTS)
        self.assertIn("maximum", str(detail["reason"]))

        canonical = self._home_frame()
        _root, runtime, ok, detail = self._run_normalizer(
            factory=lambda _count: canonical,
            input_count=ultimate.MAX_TOTAL_INPUTS - 1,
        )
        self.assertTrue(ok)
        self.assertEqual(runtime.input_count, ultimate.MAX_TOTAL_INPUTS)
        self.assertEqual(detail["zoom_input_count"], 1)
        self.assertEqual(ultimate.MAX_TOTAL_INPUTS, 16)


class UltimateCampaignExitRecoveryTests(unittest.TestCase):
    CANCEL_ROI = (60, 650, 380, 780)
    EXIT_ROI = (690, 920, 800, 1060)

    @staticmethod
    def _captured(
        root: Path,
        frame: np.ndarray,
        label: str,
        ordinal: int,
    ) -> CapturedNativeFrame:
        encoded_ok, encoded = cv2.imencode(".png", frame)
        assert encoded_ok
        payload = encoded.tobytes()
        path = root / f"{ordinal:04d}-{label}.png"
        path.write_bytes(payload)
        return CapturedNativeFrame(
            frame=frame.copy(),
            png=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
            captured_monotonic=float(ordinal),
            path=path,
        )

    @staticmethod
    def _exit_dialog_frame(
        *,
        modal_text: str = "Exit the game?",
        cancel_text: str = "Cancel",
        confirm_text: str = "Confirm",
        cancel_x: int = 100,
    ) -> np.ndarray:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            modal_text,
            (180, 520),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (255, 255, 255),
            4,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            cancel_text,
            (cancel_x, 725),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.3,
            (255, 255, 255),
            4,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            confirm_text,
            (450, 725),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.3,
            (255, 255, 255),
            4,
            cv2.LINE_AA,
        )
        return frame

    class _Runtime:
        def __init__(
            self,
            root: Path,
            frames: list[np.ndarray],
        ) -> None:
            self.root = root
            self.root.mkdir(parents=True, exist_ok=True)
            self.frames = list(frames)
            self.captures: list[CapturedNativeFrame] = []
            self.taps: list[dict[str, object]] = []
            self.backs: list[dict[str, object]] = []
            self.reconciliations: list[
                tuple[str, str, CapturedNativeFrame, str]
            ] = []
            self.action_keys: set[str] = set()
            self.input_count = 0
            self.runner = SimpleNamespace()

        def capture(self, label: str) -> CapturedNativeFrame:
            frame = self.frames.pop(0) if self.frames else self.captures[-1].frame
            captured = UltimateCampaignExitRecoveryTests._captured(
                self.root,
                frame,
                label,
                len(self.captures) + 1,
            )
            self.captures.append(captured)
            return captured

        def tap(self, source: CapturedNativeFrame, **kwargs) -> None:
            self.taps.append({"source": source, **kwargs})
            self.action_keys.add(str(kwargs["action_key"]))
            self.input_count += 1

        def back(self, source: CapturedNativeFrame, **kwargs) -> None:
            self.backs.append({"source": source, **kwargs})
            self.action_keys.add(str(kwargs["action_key"]))
            self.input_count += 1

        def reconcile(
            self,
            action_key: str,
            status: str,
            post: CapturedNativeFrame,
            reason: str,
        ) -> None:
            self.reconciliations.append((action_key, status, post, reason))

    def test_real_exit_dialog_binds_only_cancel_and_rejects_negatives(self) -> None:
        recognized, cancel_roi = ultimate.troop_training_vision.recognize_exit_dialog(
            self._exit_dialog_frame()
        )
        self.assertTrue(recognized)
        self.assertEqual(cancel_roi, self.CANCEL_ROI)
        self.assertNotEqual(cancel_roi, (400, 650, 740, 780))

        self.assertEqual(
            ultimate.troop_training_vision.recognize_exit_dialog(
                self._exit_dialog_frame(modal_text="Stay in the game?")
            ),
            (False, None),
        )
        for confusable in (
            "Exit settings. Game over?",
            "Exit the game. Please stay?",
        ):
            with self.subTest(modal_text=confusable):
                self.assertEqual(
                    ultimate.troop_training_vision.recognize_exit_dialog(
                        self._exit_dialog_frame(modal_text=confusable)
                    ),
                    (False, None),
                )
        self.assertEqual(
            ultimate.troop_training_vision.recognize_exit_dialog(
                self._exit_dialog_frame(cancel_x=410)
            ),
            (False, None),
        )

    def test_real_current_frame_campaign_exit_measurement_fixture(self) -> None:
        fixture = cv2.imread(
            str(
                ROOT
                / "tasks/assets/campaign_auto_battle/800x1280/ground-truth/"
                "campaign-exit-unhighlighted/"
                "annotated-exit-unhighlighted-from-0006-campaign-exit-home-immediate-before.png"
            ),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(fixture)
        measured_roi, score = ultimate.campaign_atlas_vision.measured_survey_target(
            fixture,
            "campaign-exit-base",
        )
        self.assertEqual(measured_roi, self.EXIT_ROI)
        self.assertGreater(score, 0.55)

    def test_normal_post_flee_route_uses_measured_exit_not_campaign_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            (session / "frames").mkdir(parents=True)
            events = session / "events.jsonl"
            campaign_frame = np.zeros((1280, 800, 3), dtype=np.uint8)
            runtime = self._Runtime(
                root,
                [
                    np.zeros((1280, 800, 3), dtype=np.uint8),
                    np.zeros((1280, 800, 3), dtype=np.uint8),
                ],
            )
            campaign = self._captured(root, campaign_frame, "campaign", 90)
            with patch.object(
                ultimate,
                "_recognize_ultimate_main",
                return_value=(300, 1170, 500, 1260),
            ), patch.object(
                ultimate,
                "_capture_until",
                return_value=campaign,
            ), patch.object(
                ultimate,
                "_campaign_context_recognized",
                return_value=True,
            ), patch.object(
                ultimate,
                "_home_nav_terminal",
                return_value=True,
            ), patch.object(
                ultimate.campaign_atlas_vision,
                "measured_survey_target",
                return_value=(self.EXIT_ROI, 0.9999316),
            ), patch.object(ultimate.time, "sleep", return_value=None):
                terminal, detail = ultimate._run_post_flee_home_route(
                    runner=runtime.runner,
                    session=session,
                    events=events,
                    reset_identity="game-day-2026-08-17",
                    post_input_delay=0,
                    runtime=runtime,
                )

        self.assertEqual(terminal, "complete_for_reset")
        self.assertEqual(len(runtime.taps), 1)
        self.assertEqual(runtime.taps[0]["target_identity"], "campaign-exit-base")
        self.assertEqual(runtime.taps[0]["target_roi"], self.EXIT_ROI)
        self.assertFalse(runtime.taps[0]["consequential"])
        self.assertEqual(
            runtime.taps[0]["source"],
            runtime.captures[1],
        )
        self.assertIn(runtime.taps[0]["source"].sha256, runtime.taps[0]["action_key"])
        self.assertFalse(
            any(
                back.get("target_identity") == "campaign-back-to-home"
                for back in runtime.backs
            )
        )
        key, status, post, _reason = runtime.reconciliations[-1]
        self.assertEqual(key, runtime.taps[0]["action_key"])
        self.assertEqual(status, "confirmed")
        self.assertIs(post, runtime.captures[-1])
        self.assertEqual(detail["home_nav_recognized"], True)
        self.assertEqual(detail["resource_delta"], {"ap": 0, "stamina": 0, "currency": 0, "items": 0})

    def test_post_flee_uc_back_transport_failure_reconciles_only_accounted_key(self) -> None:
        class BackFailsAfterAccounting(self._Runtime):
            def back(self, source, **kwargs) -> None:
                super().back(source, **kwargs)
                raise RuntimeError("synthetic UC back transport failure")

        class BackFailsBeforeAccounting(self._Runtime):
            def back(self, _source, **_kwargs) -> None:
                raise RuntimeError("synthetic pre-accounting failure")

        for runtime_type, expected_count, expected_reconciliations in (
            (BackFailsAfterAccounting, 1, 1),
            (BackFailsBeforeAccounting, 0, 0),
        ):
            with self.subTest(runtime=runtime_type.__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                session = root / "session"
                (session / "frames").mkdir(parents=True)
                events = session / "events.jsonl"
                runtime = runtime_type(
                    root,
                    [np.zeros((1280, 800, 3), dtype=np.uint8)],
                )
                with patch.object(
                    ultimate,
                    "_recognize_ultimate_main",
                    return_value=(300, 1170, 500, 1260),
                ), patch.object(
                    ultimate,
                    "utc_stamp",
                    return_value="r18-transport",
                ):
                    terminal, detail = ultimate._run_post_flee_home_route(
                        runner=runtime.runner,
                        session=session,
                        events=events,
                        reset_identity="game-day-2026-08-17",
                        post_input_delay=0,
                        runtime=runtime,
                    )

            self.assertEqual(terminal, "blocked_fail_closed")
            self.assertEqual(runtime.input_count, expected_count)
            self.assertEqual(len(runtime.reconciliations), expected_reconciliations)
            self.assertEqual(detail["uc_back_action_key"], "uc-back-r18-transport")
            self.assertEqual(detail["runtime_accounted"], expected_count == 1)
            if expected_reconciliations:
                key, status, post, _reason = runtime.reconciliations[0]
                self.assertEqual(key, "uc-back-r18-transport")
                self.assertEqual(status, "unresolved")
                self.assertIs(post, runtime.captures[0])

    def test_post_flee_uc_back_missing_or_wrong_successor_reconciles_latest_evidence(self) -> None:
        cases = (
            ("missing", None, None),
            ("wrong", "wrong", False),
        )
        for label, successor_kind, recognized in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                session = root / "session"
                (session / "frames").mkdir(parents=True)
                events = session / "events.jsonl"
                runtime = self._Runtime(
                    root,
                    [np.zeros((1280, 800, 3), dtype=np.uint8)],
                )
                successor = (
                    self._captured(
                        root,
                        np.full((1280, 800, 3), 7, dtype=np.uint8),
                        "wrong-successor",
                        2,
                    )
                    if successor_kind == "wrong"
                    else None
                )
                with patch.object(
                    ultimate,
                    "_recognize_ultimate_main",
                    return_value=(300, 1170, 500, 1260),
                ), patch.object(
                    ultimate,
                    "_capture_until",
                    return_value=successor,
                ), patch.object(
                    ultimate,
                    "_campaign_context_recognized",
                    return_value=bool(recognized),
                ), patch.object(
                    ultimate,
                    "utc_stamp",
                    return_value=f"r18-{label}",
                ):
                    terminal, detail = ultimate._run_post_flee_home_route(
                        runner=runtime.runner,
                        session=session,
                        events=events,
                        reset_identity="game-day-2026-08-17",
                        post_input_delay=0,
                        runtime=runtime,
                    )

            self.assertEqual(terminal, "blocked_fail_closed")
            self.assertEqual(detail["uc_back_action_key"], f"uc-back-r18-{label}")
            self.assertEqual(len(runtime.reconciliations), 1)
            key, status, post, _reason = runtime.reconciliations[0]
            self.assertEqual(key, detail["uc_back_action_key"])
            self.assertEqual(status, "unresolved")
            self.assertIs(post, successor or runtime.captures[0])

    def test_post_flee_uc_back_success_reconciles_exact_key_before_campaign_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session"
            (session / "frames").mkdir(parents=True)
            events = session / "events.jsonl"
            runtime = self._Runtime(
                root,
                [np.zeros((1280, 800, 3), dtype=np.uint8)],
            )
            campaign = self._captured(
                root,
                np.full((1280, 800, 3), 9, dtype=np.uint8),
                "campaign-successor",
                2,
            )
            with patch.object(
                ultimate,
                "_recognize_ultimate_main",
                return_value=(300, 1170, 500, 1260),
            ), patch.object(
                ultimate,
                "_capture_until",
                return_value=campaign,
            ), patch.object(
                ultimate,
                "_campaign_context_recognized",
                return_value=True,
            ), patch.object(
                ultimate,
                "_run_measured_campaign_exit_home_route",
                return_value=("blocked_fail_closed", {"reason": "stop after UC back"}),
            ), patch.object(
                ultimate,
                "utc_stamp",
                return_value="r18-success",
            ):
                terminal, _detail = ultimate._run_post_flee_home_route(
                    runner=runtime.runner,
                    session=session,
                    events=events,
                    reset_identity="game-day-2026-08-17",
                    post_input_delay=0,
                    runtime=runtime,
                )

        self.assertEqual(terminal, "blocked_fail_closed")
        self.assertEqual(len(runtime.reconciliations), 1)
        key, status, post, _reason = runtime.reconciliations[0]
        self.assertEqual(key, "uc-back-r18-success")
        self.assertEqual(status, "confirmed")
        self.assertIs(post, campaign)

    def test_campaign_exit_failures_reconcile_only_after_accounting(self) -> None:
        cases = (
            ("campaign_mismatch", False, True),
            ("measurement_failure", True, False),
            ("non_home_successor", True, True),
        )
        for case, campaign_ok, measured_ok in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                session = root / "session"
                (session / "frames").mkdir(parents=True)
                events = session / "events.jsonl"
                runtime = self._Runtime(
                    root,
                    [np.zeros((1280, 800, 3), dtype=np.uint8)] * 10,
                )
                measurement = (
                    (self.EXIT_ROI, 0.99)
                    if measured_ok
                    else RuntimeError("synthetic measured bind failure")
                )
                with patch.object(
                    ultimate,
                    "_campaign_context_recognized",
                    return_value=campaign_ok,
                ), patch.object(
                    ultimate.campaign_atlas_vision,
                    "measured_survey_target",
                    side_effect=(
                        None
                        if isinstance(measurement, tuple)
                        else measurement
                    )
                    if not isinstance(measurement, tuple)
                    else None,
                ) as measured:
                    if isinstance(measurement, tuple):
                        measured.return_value = measurement
                    with patch.object(
                        ultimate,
                        "_home_nav_terminal",
                        return_value=False,
                    ):
                        terminal, _detail = ultimate._run_measured_campaign_exit_home_route(
                            runtime=runtime,
                            session=session,
                            events=events,
                            reset_identity="game-day-2026-08-17",
                            post_input_delay=0,
                        )

                self.assertEqual(terminal, "blocked_fail_closed")
                if case in {"campaign_mismatch", "measurement_failure"}:
                    self.assertEqual(runtime.taps, [])
                    self.assertEqual(runtime.reconciliations, [])
                else:
                    self.assertEqual(len(runtime.taps), 1)
                    self.assertEqual(runtime.reconciliations[-1][1], "unresolved")

    def test_main_current_exit_dialog_recovers_with_two_confirmed_inputs(self) -> None:
        dialog = self._exit_dialog_frame()
        campaign_frame = cv2.imread(
            str(
                ROOT
                / "tasks/assets/campaign_auto_battle/800x1280/ground-truth/"
                "campaign-exit-unhighlighted/"
                "annotated-exit-unhighlighted-from-0006-campaign-exit-home-immediate-before.png"
            ),
            cv2.IMREAD_COLOR,
        )
        runtime_holder: list[UltimateCampaignExitRecoveryTests._Runtime] = []
        frames = [dialog, dialog, campaign_frame, campaign_frame, np.zeros((1280, 800, 3), dtype=np.uint8)]

        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [SimpleNamespace(serial="emulator-5554", state="device")]

            def get_state(self) -> str:
                return "device"

        class FakeRuntime(self._Runtime):
            def __init__(self, runner, session: Path, *, execute: bool) -> None:
                super().__init__(session / "frames", frames)
                self.runner = runner
                self.execute = execute
                runtime_holder.append(self)

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
                    reason="not already_completed",
                ),
            ), patch.object(
                ultimate,
                "_campaign_context_recognized",
                return_value=True,
            ), patch.object(
                ultimate,
                "_home_nav_terminal",
                return_value=True,
            ), patch.object(
                ultimate.campaign_atlas_vision,
                "measured_survey_target",
                return_value=(self.EXIT_ROI, 0.9999316),
            ), patch.object(
                ultimate,
                "_run_daily_route",
                side_effect=AssertionError("Challenge route must not run"),
            ), patch.object(
                ultimate,
                "recognize_reset_popup",
                side_effect=AssertionError("VIP route must not run"),
            ), patch.object(ultimate.time, "sleep", return_value=None):
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
            self.assertEqual(code, 0)
            self.assertEqual(len(sessions), 1)
            result = json.loads((sessions[0] / "result.json").read_text(encoding="utf-8"))

        runtime = runtime_holder[0]
        self.assertEqual(result["terminal"], "complete_for_reset")
        self.assertTrue(result["exit_dialog_recovery"])
        self.assertEqual(result["input_count"], 2)
        self.assertEqual(result["recovery_input_count"], 2)
        self.assertEqual(len(runtime.taps), 2)
        self.assertEqual(
            [tap["target_identity"] for tap in runtime.taps],
            ["exit-dialog-cancel", "campaign-exit-base"],
        )
        self.assertTrue(all(tap["consequential"] is False for tap in runtime.taps))
        self.assertTrue(all("confirm" not in str(tap["target_identity"]).casefold() for tap in runtime.taps))
        self.assertEqual(
            [status for _key, status, _post, _reason in runtime.reconciliations],
            ["confirmed", "confirmed"],
        )
        self.assertIs(runtime.reconciliations[0][2], runtime.captures[2])
        self.assertIs(runtime.reconciliations[1][2], runtime.captures[4])
        self.assertEqual(result["resource_delta"], {"ap": 0, "stamina": 0, "currency": 0, "items": 0})

    def test_main_campaign_exit_home_only_returns_home_with_single_measured_tap(
        self,
    ) -> None:
        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [SimpleNamespace(serial="emulator-5554", state="device")]

            def get_state(self) -> str:
                return "device"

        class FakeRuntime(self._Runtime):
            def __init__(self, runner, session: Path, *, execute: bool) -> None:
                super().__init__(
                    session / "frames", [np.zeros((1280, 800, 3), dtype=np.uint8)]
                )
                self.runner = runner
                self.execute = execute

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(ultimate, "ADBRunner", FakeRunner), patch.object(
                ultimate, "LocalBlueStacksRuntime", FakeRuntime
            ), patch.object(
                ultimate, "is_permitted_local_bluestacks_serial", return_value=True
            ), patch.object(
                ultimate, "require_campaign_home_atlas_building"
            ), patch.object(
                ultimate, "_campaign_context_recognized", return_value=True
            ), patch.object(
                ultimate, "_home_nav_terminal", return_value=True
            ), patch.object(
                ultimate.campaign_atlas_vision,
                "measured_survey_target",
                return_value=(self.EXIT_ROI, 0.9999316),
            ), patch.object(ultimate.time, "sleep", return_value=None):
                code = ultimate.main(
                    [
                        "--adb",
                        "unused-adb",
                        "--serial",
                        "emulator-5554",
                        "--campaign-exit-home-only",
                        "--execute",
                        "--yes",
                        "--output-directory",
                        str(output),
                        "--reset-identity",
                        "game-day-2026-08-17",
                    ]
                )

            self.assertEqual(code, 0)
            sessions = list(output.glob("nav-*"))
            self.assertEqual(len(sessions), 1)
            session = sessions[0]
            retained, frame_paths = require_operator_evidence(session)
            self.assertEqual(retained["terminal"], "complete_for_reset")
            self.assertTrue(retained["dispatch"])
            self.assertEqual(retained["input_count"], 1)
            self.assertIn("frames/campaign-exit-immediate-before.png", frame_paths)
            self.assertIn("frames/canonical-home-terminal.png", frame_paths)
            events = [
                json.loads(line)
                for line in (session / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            self.assertTrue(
                any(event["type"] == "campaign_exit_home_only" for event in events)
            )

    def test_main_campaign_exit_home_only_fails_closed_off_campaign(self) -> None:
        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [SimpleNamespace(serial="emulator-5554", state="device")]

            def get_state(self) -> str:
                return "device"

        class FakeRuntime(self._Runtime):
            def __init__(self, runner, session: Path, *, execute: bool) -> None:
                super().__init__(
                    session / "frames", [np.zeros((1280, 800, 3), dtype=np.uint8)]
                )
                self.runner = runner
                self.execute = execute

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(ultimate, "ADBRunner", FakeRunner), patch.object(
                ultimate, "LocalBlueStacksRuntime", FakeRuntime
            ), patch.object(
                ultimate, "is_permitted_local_bluestacks_serial", return_value=True
            ), patch.object(
                ultimate, "require_campaign_home_atlas_building"
            ), patch.object(
                ultimate, "_campaign_context_recognized", return_value=False
            ), patch.object(ultimate.time, "sleep", return_value=None):
                code = ultimate.main(
                    [
                        "--adb",
                        "unused-adb",
                        "--serial",
                        "emulator-5554",
                        "--campaign-exit-home-only",
                        "--execute",
                        "--yes",
                        "--output-directory",
                        str(output),
                        "--reset-identity",
                        "game-day-2026-08-17",
                    ]
                )

            self.assertEqual(code, 3)
            session = next(iter(output.glob("nav-*")))
            retained, _frame_paths = require_operator_evidence(session)
            self.assertEqual(retained["terminal"], ultimate.TERMINAL_BLOCKED)
            self.assertEqual(retained["input_count"], 0)
            self.assertEqual(
                retained["reason"],
                "Campaign exit immediate-before was not positively recognized",
            )

    def test_navigation_only_exit_dialog_is_zero_input_fail_closed(self) -> None:
        dialog = self._exit_dialog_frame()

        class FakeRunner:
            def __init__(self, *_args) -> None:
                pass

            def list_devices(self):
                return [SimpleNamespace(serial="emulator-5554", state="device")]

            def get_state(self) -> str:
                return "device"

        runtime_holder: list[object] = []

        class FakeRuntime:
            def __init__(self, runner, runtime_session: Path, *, execute: bool) -> None:
                runtime_session.mkdir(parents=True, exist_ok=True)
                self.runner = runner
                self.session = runtime_session
                self.execute = execute
                self.input_count = 0
                self._captured = UltimateCampaignExitRecoveryTests._captured(
                    runtime_session,
                    dialog,
                    "campaign-resume-source",
                    1,
                )
                runtime_holder.append(self)

            def capture(self, _label: str) -> CapturedNativeFrame:
                return self._captured

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
                "troop_training_vision",
            ) as vision:
                vision.recognize_exit_dialog.side_effect = AssertionError(
                    "navigation-only must not run exit-dialog recovery"
                )
                with patch.object(
                    ultimate,
                    "recognize_reset_popup",
                    return_value={"recognized": False},
                ), patch.object(
                    ultimate,
                    "_recognize_ultimate_main",
                    return_value=None,
                ), patch.object(
                    ultimate,
                    "_bind_lineup_challenge_button",
                    return_value=None,
                ), patch.object(
                    ultimate,
                    "_recognize_active_battle",
                    return_value=None,
                ), patch.object(
                    ultimate,
                    "_bind_flee_warning_button",
                    return_value=None,
                ), patch.object(
                    ultimate,
                    "_bind_ultimate_challenge_entry",
                    return_value=SimpleNamespace(
                        campaign_screen_recognized=False,
                        entry_control_visible=False,
                        entry_roi=None,
                        source_frame_sha256="dialog",
                    ),
                ), patch.object(
                    ultimate,
                    "_home_nav_terminal",
                    return_value=False,
                ):
                    code = ultimate.main(
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
            sessions = list(output.glob("nav-*"))
            self.assertEqual(len(sessions), 1)
            result = json.loads((sessions[0] / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(code, 3)
        self.assertEqual(runtime_holder[0].input_count, 0)
        self.assertNotEqual(result["terminal"], "complete_for_reset")
        self.assertTrue(result["navigation_only"])
        self.assertFalse(result["dispatch"])


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
            self.assertEqual(
                result["reason"],
                "fresh template Home was not positively recognized",
            )
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
        lease = lease_context or {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
        }
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
            "development_session": SimpleNamespace(
                session_directory=Path("outer-development-session"),
                run_action=lambda **_kwargs: None,
            ),
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
                "missing queue marker",
                {"active_flow_id": FLOW_ID},
                valid_lease,
            ),
            (
                "missing lease marker",
                valid_queue,
                {
                    key: value
                    for key, value in valid_lease.items()
                    if key != "development_session"
                },
            ),
            (
                "queue marker false",
                {**valid_queue, "development_session": False},
                valid_lease,
            ),
            (
                "lease marker false",
                valid_queue,
                {**valid_lease, "development_session": False},
            ),
            (
                "lease marker wrong type",
                valid_queue,
                {**valid_lease, "development_session": SimpleNamespace()},
            ),
            (
                "missing owner",
                valid_queue,
                {key: value for key, value in valid_lease.items() if key != "owner"},
            ),
            ("empty owner", valid_queue, {**valid_lease, "owner": "  "}),
            (
                "released runtime",
                valid_queue,
                {**valid_lease, "runtime_ownership_state": "released"},
            ),
            (
                "missing runtime ownership",
                valid_queue,
                {
                    key: value
                    for key, value in valid_lease.items()
                    if key != "runtime_ownership_state"
                },
            ),
            (
                "missing ceiling",
                valid_queue,
                {key: value for key, value in valid_lease.items() if key != "max_inputs"},
            ),
            ("invalid ceiling", valid_queue, {**valid_lease, "max_inputs": "16"}),
            ("smaller ceiling", valid_queue, {**valid_lease, "max_inputs": 12}),
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
                self.assertFalse(
                    (Path(directory) / "artifacts" / FLOW_ID).exists()
                )

    def test_daily_wrapper_accepts_legacy_context_and_propagates_explicit_ceiling(
        self,
    ) -> None:
        queue = {
            "active_flow_id": FLOW_ID,
            "flows": [
                {
                    "flow_id": FLOW_ID,
                    "maximum_live_attempts": 4,
                    "live_attempts": [{"diagnosis": "legacy context"}],
                }
            ]
        }
        lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
        }
        with tempfile.TemporaryDirectory() as directory:
            command, _load_state, _record_home, _save_state = self._run_wrapper(
                Path(directory),
                terminal="already_completed",
                home_nav_recognized=True,
                queue_context=queue,
                lease_context=lease,
            )
        self.assertEqual(command[command.index("--max-total-inputs") + 1], "16")

    def test_daily_wrapper_rejects_legacy_missing_flows_before_child(self) -> None:
        queue = {}
        lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_pnsctl = self.FakePnsctl(root / "artifacts")
            with patch.object(
                delivery, "_pnsctl", return_value=fake_pnsctl
            ), patch.object(delivery.subprocess, "run") as child:
                with self.assertRaisesRegex(RuntimeError, "flows"):
                    delivery.run_ultimate_challenge_daily(queue, lease)
            child.assert_not_called()
            self.assertFalse((root / "artifacts" / FLOW_ID).exists())

    def test_daily_wrapper_rejects_legacy_missing_authority_or_ceiling_before_child(
        self,
    ) -> None:
        queue = {
            "active_flow_id": FLOW_ID,
            "flows": [
                {
                    "flow_id": FLOW_ID,
                    "maximum_live_attempts": 4,
                    "live_attempts": [{"diagnosis": "legacy context"}],
                }
            ]
        }
        valid_lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
        }
        invalid_leases = (
            (
                "missing runtime ownership",
                {
                    key: value
                    for key, value in valid_lease.items()
                    if key != "runtime_ownership_state"
                },
            ),
            (
                "missing max ceiling",
                {
                    key: value
                    for key, value in valid_lease.items()
                    if key != "max_inputs"
                },
            ),
        )
        for label, lease in invalid_leases:
            with self.subTest(context=label), tempfile.TemporaryDirectory() as directory:
                fake_pnsctl = self.FakePnsctl(Path(directory) / "artifacts")
                with patch.object(
                    delivery, "_pnsctl", return_value=fake_pnsctl
                ), patch.object(delivery.subprocess, "run") as child:
                    with self.assertRaisesRegex(RuntimeError, "Ultimate Challenge"):
                        delivery.run_ultimate_challenge_daily(queue, lease)
                child.assert_not_called()
                self.assertFalse(
                    (Path(directory) / "artifacts" / FLOW_ID).exists()
                )

    def test_legacy_flow_context_requires_exactly_one_matching_flow(self) -> None:
        invalid_queues = (
            ("missing flows", {}),
            ("null flows", {"flows": None}),
            ("non-list flows", {"flows": {"flow_id": FLOW_ID}}),
            ("empty flows", {"flows": []}),
            ("wrong flow", {"flows": [{"flow_id": "OTHER-FLOW"}]}),
            (
                "duplicate matching flows",
                {"flows": [{"flow_id": FLOW_ID}, {"flow_id": FLOW_ID}]},
            ),
        )
        for label, queue in invalid_queues:
            with self.subTest(context=label):
                with patch.object(
                    delivery,
                    "_pnsctl",
                    return_value=self.FakePnsctl(Path(".")),
                ):
                    with self.assertRaisesRegex(RuntimeError, "legacy flow"):
                        delivery._legacy_daily_flow(queue)

    def _run_navigation_wrapper(
        self,
        root: Path,
        *,
        queue_context: dict,
        lease_context: dict,
    ) -> list[str]:
        fake_pnsctl = self.FakePnsctl(root / "artifacts")
        commands: list[list[str]] = []
        result = {
            "flow_id": FLOW_ID,
            "terminal": "navigation_only_complete",
            "status": "navigation_only_complete",
            "terminal_runtime_state": "ultimate_challenge_entry_recognized",
        }

        def fake_run(command, **_kwargs):
            commands.append(command)
            return __import__("subprocess").CompletedProcess(
                command,
                0,
                "",
                "",
            )

        with patch.object(
            delivery, "_pnsctl", return_value=fake_pnsctl
        ), patch.object(
            delivery.subprocess, "run", side_effect=fake_run
        ), patch.object(
            delivery,
            "require_operator_evidence",
            return_value=(result, ["frames/source.png"]),
        ):
            delivery.run_ultimate_challenge_navigation_only(
                queue_context,
                lease_context,
            )
        return commands[0]

    def test_navigation_wrapper_accepts_minimal_development_session_context(
        self,
    ) -> None:
        queue = {"active_flow_id": FLOW_ID, "development_session": True}
        lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
            "development_session": SimpleNamespace(
                session_directory=Path("outer-development-session"),
                run_action=lambda **_kwargs: None,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            command = self._run_navigation_wrapper(
                Path(directory),
                queue_context=queue,
                lease_context=lease,
            )
            session_root = Path(directory) / "artifacts" / FLOW_ID
            self.assertEqual(len(list(session_root.glob("nav-ultimate-challenge-*"))), 1)
        self.assertIn("--navigation-only", command)
        self.assertEqual(
            command[command.index("--max-total-inputs") + 1],
            "16",
        )

    def test_navigation_wrapper_rejects_invalid_development_session_context_before_child(
        self,
    ) -> None:
        valid_queue = {"active_flow_id": FLOW_ID, "development_session": True}
        valid_lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
            "development_session": True,
        }
        invalid_contexts = (
            (
                "wrong flow",
                {**valid_queue, "active_flow_id": "OTHER-FLOW"},
                valid_lease,
            ),
            ("missing flow", {"development_session": True}, valid_lease),
            (
                "missing queue marker",
                {"active_flow_id": FLOW_ID},
                valid_lease,
            ),
            (
                "missing lease marker",
                valid_queue,
                {
                    key: value
                    for key, value in valid_lease.items()
                    if key != "development_session"
                },
            ),
            (
                "queue marker false",
                {**valid_queue, "development_session": False},
                valid_lease,
            ),
            (
                "lease marker false",
                valid_queue,
                {**valid_lease, "development_session": False},
            ),
            (
                "lease marker wrong type",
                valid_queue,
                {**valid_lease, "development_session": SimpleNamespace()},
            ),
            (
                "missing owner",
                valid_queue,
                {key: value for key, value in valid_lease.items() if key != "owner"},
            ),
            ("empty owner", valid_queue, {**valid_lease, "owner": "  "}),
            (
                "released runtime",
                valid_queue,
                {**valid_lease, "runtime_ownership_state": "released"},
            ),
            (
                "missing runtime ownership",
                valid_queue,
                {
                    key: value
                    for key, value in valid_lease.items()
                    if key != "runtime_ownership_state"
                },
            ),
            (
                "missing ceiling",
                valid_queue,
                {key: value for key, value in valid_lease.items() if key != "max_inputs"},
            ),
            ("invalid ceiling", valid_queue, {**valid_lease, "max_inputs": "16"}),
            ("smaller ceiling", valid_queue, {**valid_lease, "max_inputs": 12}),
            ("over ceiling", valid_queue, {**valid_lease, "max_inputs": 17}),
        )

        for label, queue, lease in invalid_contexts:
            with self.subTest(context=label), tempfile.TemporaryDirectory() as directory:
                fake_pnsctl = self.FakePnsctl(Path(directory) / "artifacts")
                with patch.object(
                    delivery, "_pnsctl", return_value=fake_pnsctl
                ), patch.object(delivery.subprocess, "run") as child:
                    with self.assertRaisesRegex(RuntimeError, "Ultimate Challenge"):
                        delivery.run_ultimate_challenge_navigation_only(queue, lease)
                child.assert_not_called()
                self.assertFalse(
                    (Path(directory) / "artifacts" / FLOW_ID).exists()
                )

    def test_navigation_wrapper_accepts_legacy_context_and_propagates_explicit_ceiling(
        self,
    ) -> None:
        queue = {
            "active_flow_id": FLOW_ID,
            "flows": [
                {
                    "flow_id": FLOW_ID,
                    "maximum_live_attempts": 4,
                    "live_attempts": [{"diagnosis": "legacy context"}],
                }
            ]
        }
        lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
        }
        with tempfile.TemporaryDirectory() as directory:
            command = self._run_navigation_wrapper(
                Path(directory),
                queue_context=queue,
                lease_context=lease,
            )
        self.assertEqual(command[command.index("--max-total-inputs") + 1], "16")

    def test_navigation_wrapper_rejects_legacy_missing_flows_before_child(
        self,
    ) -> None:
        queue = {}
        lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_pnsctl = self.FakePnsctl(root / "artifacts")
            with patch.object(
                delivery, "_pnsctl", return_value=fake_pnsctl
            ), patch.object(delivery.subprocess, "run") as child:
                with self.assertRaisesRegex(RuntimeError, "flows"):
                    delivery.run_ultimate_challenge_navigation_only(queue, lease)
            child.assert_not_called()
            self.assertFalse((root / "artifacts" / FLOW_ID).exists())

    def test_navigation_wrapper_rejects_legacy_missing_authority_or_ceiling_before_child(
        self,
    ) -> None:
        queue = {
            "flows": [
                {
                    "flow_id": FLOW_ID,
                    "maximum_live_attempts": 4,
                    "live_attempts": [{"diagnosis": "legacy context"}],
                }
            ]
        }
        valid_lease = {
            "owner": "test-owner",
            "runtime_ownership_state": "held",
            "max_inputs": 16,
        }
        invalid_leases = (
            (
                "missing runtime ownership",
                {
                    key: value
                    for key, value in valid_lease.items()
                    if key != "runtime_ownership_state"
                },
            ),
            (
                "missing max ceiling",
                {
                    key: value
                    for key, value in valid_lease.items()
                    if key != "max_inputs"
                },
            ),
        )
        for label, lease in invalid_leases:
            with self.subTest(context=label), tempfile.TemporaryDirectory() as directory:
                fake_pnsctl = self.FakePnsctl(Path(directory) / "artifacts")
                with patch.object(
                    delivery, "_pnsctl", return_value=fake_pnsctl
                ), patch.object(delivery.subprocess, "run") as child:
                    with self.assertRaisesRegex(RuntimeError, "Ultimate Challenge"):
                        delivery.run_ultimate_challenge_navigation_only(queue, lease)
                child.assert_not_called()
                self.assertFalse(
                    (Path(directory) / "artifacts" / FLOW_ID).exists()
                )

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
