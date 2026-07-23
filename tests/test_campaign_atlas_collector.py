from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import unittest

from scripts import campaign_atlas_bluestacks


class CampaignAtlasCollectorTests(unittest.TestCase):
    def test_dry_run_is_evidence_required_and_zero_input(self) -> None:
        payload = campaign_atlas_bluestacks.build_dry_run_payload()
        self.assertEqual(payload["disposition"], "evidence_required")
        self.assertFalse(payload["transport_dispatched"])
        self.assertEqual(payload["transport_input_count"], 0)
        self.assertEqual(payload["native_frames_acquired"], 0)
        self.assertEqual(payload["evidence_artifacts"], [])
        self.assertFalse(payload["atlas_created"])

    def test_cli_prints_only_offline_report(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = campaign_atlas_bluestacks.main(["dry-run"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["transport_input_count"], 0)

    def test_cli_rejects_live_transport_options(self) -> None:
        for option in ("--execute", "--serial", "--adb"):
            with self.subTest(option=option), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                campaign_atlas_bluestacks.main(["dry-run", option])

    def test_collector_source_has_no_runtime_transport_imports(self) -> None:
        source = Path(campaign_atlas_bluestacks.__file__).read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "ADBRunner", "LocalBlueStacksRuntime", "input tap"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
