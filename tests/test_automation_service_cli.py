from __future__ import annotations

import contextlib
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from safe_action_core import SafetyStore

from automation_service.cli import main


class AutomationServiceCliTests(unittest.TestCase):
    def test_status_is_local_and_disabled(self) -> None:
        output = StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["status"]), 0)
        self.assertIn('"registration_status": "NOT_REGISTERED"', output.getvalue())
        self.assertIn('"scheduler_eligible": false', output.getvalue())
        self.assertIn('"registered_flows": []', output.getvalue())
        self.assertIn('"disabled_flows"', output.getvalue())

    def test_automatic_mode_is_rejected(self) -> None:
        with contextlib.redirect_stderr(StringIO()):
            self.assertEqual(main(["--mode", "automatic", "status"]), 2)

    def test_disabled_health_probes_database_and_supervised_fake_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "service.sqlite3"
            missing_output = StringIO()
            with contextlib.redirect_stdout(missing_output):
                self.assertEqual(
                    main(
                        [
                            "--mode",
                            "disabled",
                            "--state-path",
                            str(state_path),
                            "health",
                        ]
                    ),
                    1,
                )
            self.assertIn('"database_ok": false', missing_output.getvalue())
            store = SafetyStore(state_path)
            store.close()
            output = StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "--mode",
                            "disabled",
                            "--state-path",
                            str(state_path),
                            "health",
                        ]
                    ),
                    0,
                )
            self.assertIn('"healthy": true', output.getvalue())
        with contextlib.redirect_stderr(StringIO()):
            self.assertEqual(main(["--mode", "supervised", "--adapter", "fake", "health"]), 2)

    def test_observe_fails_when_adapter_has_no_frame(self) -> None:
        output = StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--adapter", "replay", "observe"]), 1)
        self.assertIn('"observed": false', output.getvalue())

    def test_pnsctl_offline_delegation_preserves_disabled_status(self) -> None:
        from scripts.pnsctl import main as pnsctl_main

        output = StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(pnsctl_main(["automation-service", "status"]), 0)
        self.assertIn('"registered_flows": []', output.getvalue())


if __name__ == "__main__":
    unittest.main()

