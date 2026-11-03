"""Executable command and operator-evidence integrity tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import pnsctl
from scripts.flow_delivery_evidence import (
    FlowEvidenceIntegrityError,
    REQUIRED_OPERATOR_ARTIFACTS,
    require_operator_evidence,
)


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
        from scripts import flow_delivery_campaign_bluestacks as campaign
        from scripts import flow_delivery_ultimate_challenge_bluestacks as ultimate

        cases = (
            (
                campaign,
                campaign.run_campaign_navigation_only,
                {"flows": [{"flow_id": campaign.FLOW_ID, "live_attempts": []}]},
                {"owner": "test-owner", "max_inputs": 6},
                campaign.FLOW_ID,
            ),
            (
                ultimate,
                ultimate.run_ultimate_challenge_navigation_only,
                {"active_flow_id": ultimate.FLOW_ID, "development_session": True},
                {
                    "owner": "test-owner",
                    "runtime_ownership_state": "held",
                    "max_inputs": 16,
                    "development_session": True,
                },
                ultimate.FLOW_ID,
            ),
        )
        for module, run, queue, lease, flow_id in cases:
            with self.subTest(flow=flow_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                child = subprocess.CompletedProcess([], 0, "", "")
                with patch.object(pnsctl, "BLUESTACKS_ARTIFACT_ROOT", root), patch.object(
                    module.subprocess, "run", return_value=child
                ), patch.object(module, "_prepare_canonical_home", create=True):
                    with self.assertRaisesRegex(pnsctl.OperatorError, "evidence-integrity"):
                        run(queue, lease)
                created = sorted(
                    path.name for path in (root / flow_id).rglob("*") if path.is_file()
                )
                self.assertEqual(created, ["operator-stderr.log", "operator-stdout.log"])




if __name__ == "__main__":
    unittest.main()
