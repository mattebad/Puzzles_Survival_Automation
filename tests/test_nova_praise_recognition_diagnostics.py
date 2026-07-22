"""Hermetic tests for offline Nova recognition diagnostics."""

from __future__ import annotations

import unittest

import numpy as np

from scripts.nova_praise_recognition_diagnostics import (
    diagnose_frame,
    format_human_report,
)


class NovaPraiseRecognitionDiagnosticsTests(unittest.TestCase):
    def test_synthetic_non_nova_frame_reports_structure_and_non_bind(self) -> None:
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        reports = diagnose_frame(frame, frame_name="synthetic-blank.png")
        self.assertEqual(len(reports), 2)
        modes = {report["mode"] for report in reports}
        self.assertEqual(modes, {"provenanced", "initial-unprovenanced"})
        required_keys = {
            "frame",
            "mode",
            "screen_state",
            "recognized",
            "nova_bound",
            "bind_method",
            "reject_gate",
            "template",
            "radial",
            "targets",
        }
        for report in reports:
            self.assertTrue(required_keys.issubset(report.keys()))
            self.assertFalse(report["nova_bound"])
            self.assertNotEqual(report["reject_gate"], "bound")
            template = report["template"]
            for key in (
                "accepted",
                "score",
                "margin",
                "search_roi",
                "match_roi",
                "reject_reason",
            ):
                self.assertIn(key, template)
            radial = report["radial"]
            self.assertIn("supporting", radial)
            self.assertIn("rejected_or_missing", radial)
            # Blank frame must fail with a concrete template or radial reject reason.
            self.assertTrue(
                template.get("reject_reason")
                or report["reject_gate"] not in ("bound", ""),
                msg=f"expected concrete reject, got {report['reject_gate']!r}",
            )
        text = format_human_report(reports)
        self.assertIn("synthetic-blank.png", text)
        self.assertIn("gate=", text)


if __name__ == "__main__":
    unittest.main()
