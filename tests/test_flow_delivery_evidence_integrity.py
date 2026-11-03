"""Executable command and operator-evidence integrity tests."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.flow_delivery_evidence import (
    FlowEvidenceIntegrityError,
    REQUIRED_OPERATOR_ARTIFACTS,
    require_operator_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_complete_operator_session(root: Path) -> None:
    (root / "result.json").write_text(
        json.dumps({"status": "completed", "terminal": "navigation_only_complete"}) + "\n",
        encoding="utf-8",
    )
    for name in REQUIRED_OPERATOR_ARTIFACTS:
        (root / name).write_text(json.dumps({"event": name}) + "\n", encoding="utf-8")
    frames = root / "frames"
    frames.mkdir()
    (frames / "frame-0001.png").write_bytes(b"nonempty-operator-frame")


class FlowDeliveryEvidenceIntegrityTests(unittest.TestCase):
    def test_complete_operator_evidence_is_returned_without_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_complete_operator_session(root)
            result, frames = require_operator_evidence(root)
        self.assertEqual(result["terminal"], "navigation_only_complete")
        self.assertEqual(frames, ["frames/frame-0001.png"])

    def test_missing_and_zero_byte_evidence_fail_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_complete_operator_session(root)
            (root / "journal.jsonl").unlink()
            with self.assertRaisesRegex(FlowEvidenceIntegrityError, "missing"):
                require_operator_evidence(root)
            (root / "journal.jsonl").write_bytes(b"")
            with self.assertRaisesRegex(FlowEvidenceIntegrityError, "zero-byte"):
                require_operator_evidence(root)

    def test_missing_frames_and_result_fail_without_fallback_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_complete_operator_session(root)
            for frame in (root / "frames").glob("*.png"):
                frame.unlink()
            with self.assertRaisesRegex(FlowEvidenceIntegrityError, "frames"):
                require_operator_evidence(root)
            (root / "result.json").unlink()
            with self.assertRaisesRegex(FlowEvidenceIntegrityError, "result"):
                require_operator_evidence(root)

    def test_campaign_and_ultimate_wrappers_do_not_create_placeholder_evidence(self) -> None:
        for path in (
            ROOT / "scripts" / "flow_delivery_campaign_bluestacks.py",
            ROOT / "scripts" / "flow_delivery_ultimate_challenge_bluestacks.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn("require_operator_evidence", source)
            self.assertNotIn('write_text("", encoding="utf-8")', source)
            self.assertNotIn("operator-terminal.png", source)
            self.assertNotIn('_run_fixed_bluestacks_adb("exec-out", "screencap"', source)




if __name__ == "__main__":
    unittest.main()
