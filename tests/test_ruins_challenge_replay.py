"""Focused offline tests for the retained Ruins challenge replay CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import ruins_challenge_replay as replay
from tasks.ruins_challenge import (
    RuinsAvailability,
    RuinsChallengeRow,
    RuinsChestState,
    RuinsControlState,
    RuinsScreenObservation,
)


def _native_png(path: Path, *, color: tuple[int, int, int]) -> bytes:
    frame = np.zeros((1280, 800, 3), dtype=np.uint8)
    frame[:, :] = color
    encoded, buffer = cv2.imencode(".png", frame)
    if not encoded:
        raise AssertionError("test PNG encoding failed")
    path.write_bytes(buffer.tobytes())
    return path.read_bytes()


def _recognition(frame: np.ndarray, *, reset_identity: str | None = None):
    row = RuinsChallengeRow(
        "Hero Challenge",
        "Mon",
        RuinsAvailability.AVAILABLE,
        6,
        60,
        None,
        RuinsControlState.VISIBLE_ENABLED,
        RuinsChestState.UNKNOWN,
        (18, 220, 780, 410),
        reset_identity=reset_identity,
    )
    observation = RuinsScreenObservation(
        True,
        "RUINS_CHALLENGE",
        True,
        1234,
        RuinsControlState.VISIBLE_ENABLED,
        RuinsControlState.VISIBLE_ENABLED,
        RuinsControlState.VISIBLE_ENABLED,
        (row,),
        "none",
        "pixel-hash",
        reset_identity,
    )
    return SimpleNamespace(
        observation=observation,
        targets=(("challenge:Hero Challenge", (560, 290, 780, 390)),),
    )


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


class RuinsChallengeReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "retained"
        self.root.mkdir()
        self.frames = self.root / "frames"
        self.frames.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_directory_replay_is_sorted_and_compact_with_file_hashes(self) -> None:
        first = self.frames / "002-second.png"
        second = self.frames / "001-first.png"
        first_bytes = _native_png(first, color=(1, 2, 3))
        second_bytes = _native_png(second, color=(4, 5, 6))

        before = _tree_snapshot(self.root)

        def reject_live_command(*args, **kwargs):  # type: ignore[no-untyped-def]
            command = f"{args!r} {kwargs!r}".lower()
            if any(token in command for token in ("adb", "hd-adb", "pnsctl")):
                raise AssertionError(f"replay attempted a live command: {command}")
            raise AssertionError(f"unexpected subprocess command: {command}")

        # The recognizer is guarded here so this test remains fast; a real
        # recognizer may legitimately use pytesseract's local subprocess.
        with patch.object(replay, "recognize_ruins_frame", side_effect=_recognition) as recognizer, patch.object(
            subprocess, "run", side_effect=reject_live_command
        ):
            payload = replay.replay_frames(frames_dir=self.frames, allowed_roots=(self.root,))

        self.assertEqual(payload["frame_count"], 2)
        self.assertEqual([item["order"] for item in payload["frames"]], [1, 2])
        self.assertEqual(
            [item["path"] for item in payload["frames"]],
            [(self.frames / "001-first.png").as_posix(), (self.frames / "002-second.png").as_posix()],
        )
        self.assertEqual(payload["frames"][0]["sha256"], hashlib.sha256(second_bytes).hexdigest())
        self.assertEqual(payload["frames"][1]["sha256"], hashlib.sha256(first_bytes).hexdigest())
        self.assertEqual(payload["frames"][0]["screen_identity"], "RUINS_CHALLENGE")
        self.assertEqual(payload["frames"][0]["rows"][0]["identity"], "Hero Challenge")
        self.assertEqual(payload["frames"][0]["rows"][0]["availability"], "available")
        self.assertEqual(payload["frames"][0]["targets"][0]["roi"], [560, 290, 780, 390])
        self.assertEqual(replay.serialize_replay(payload), replay.serialize_replay(payload))
        self.assertEqual(recognizer.call_count, 2)
        self.assertEqual(_tree_snapshot(self.root), before)
        self.assertNotIn("subprocess", replay.__dict__)
        self.assertNotIn("scripts.bluestacks_native_runtime", replay.__dict__)
        self.assertNotIn("scripts.pnsctl", replay.__dict__)

    def test_explicit_paths_preserve_order_and_cli_json_is_parseable(self) -> None:
        one = self.frames / "one.png"
        two = self.frames / "two.png"
        _native_png(one, color=(10, 11, 12))
        _native_png(two, color=(13, 14, 15))
        with patch.object(replay, "recognize_ruins_frame", side_effect=_recognition):
            payload = replay.replay_frames((two, one), allowed_roots=(self.root,))
        self.assertEqual([item["path"] for item in payload["frames"]], [two.as_posix(), one.as_posix()])

        with patch.object(replay, "recognize_ruins_frame", side_effect=_recognition), patch.object(
            replay, "RETAINED_ROOTS", (self.root,)
        ), patch("sys.stdout.write") as output:
            self.assertEqual(replay.main(["--frames-dir", str(self.frames)]), 0)
        emitted = "".join(call.args[0] for call in output.call_args_list)
        self.assertEqual(json.loads(emitted)["frame_count"], 2)

    def test_rejects_empty_dir_bad_extension_escape_and_nonnative_dimensions(self) -> None:
        with self.assertRaisesRegex(replay.ReplayError, "empty"):
            replay.resolve_frame_paths(frames_dir=self.frames, allowed_roots=(self.root,))

        bad = self.frames / "not-a-frame.jpg"
        bad.write_bytes(b"junk")
        with self.assertRaisesRegex(replay.ReplayError, "unsupported extension"):
            replay.resolve_frame_paths(frames_dir=self.frames, allowed_roots=(self.root,))

        outside = Path(self.temp.name) / "outside.png"
        _native_png(outside, color=(7, 8, 9))
        with self.assertRaisesRegex(replay.ReplayError, "outside allowed retained roots"):
            replay.resolve_frame_paths((outside,), allowed_roots=(self.root,))

        png_directory = self.root / "directory.png"
        png_directory.mkdir()
        with self.assertRaisesRegex(replay.ReplayError, "not a file"):
            replay.resolve_frame_paths((png_directory,), allowed_roots=(self.root,))

        wrong = self.frames / "wrong.png"
        wrong_frame = np.zeros((640, 800, 3), dtype=np.uint8)
        encoded, buffer = cv2.imencode(".png", wrong_frame)
        self.assertTrue(encoded)
        wrong.write_bytes(buffer.tobytes())
        with self.assertRaisesRegex(replay.ReplayError, "native 800x1280"):
            replay.resolve_frame_paths((wrong,), allowed_roots=(self.root,))

    def test_rejects_mixed_sources_and_duplicate_explicit_paths(self) -> None:
        frame = self.frames / "frame.png"
        _native_png(frame, color=(20, 21, 22))
        with self.assertRaisesRegex(replay.ReplayError, "not both"):
            replay.resolve_frame_paths((frame,), frames_dir=self.frames, allowed_roots=(self.root,))
        with self.assertRaisesRegex(replay.ReplayError, "duplicate"):
            replay.resolve_frame_paths((frame, frame), allowed_roots=(self.root,))


if __name__ == "__main__":
    unittest.main()
