"""An explicit daily repeat does not unlock cooldowns or erase scheduled work."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation_service.contracts import FlowSpec
from automation_service.state import BotStateManager
from scripts import flow_delivery_enhancement_bluestacks as delivery
from scripts import pnsctl
from tests.support.enhancement_family import write_reset_occurrence_state

FLOW_ID = delivery.FLOW_ID


class AuthorizedDailyRepeatTests(unittest.TestCase):
    CURRENT = "local-2026-10-29-enhancement-family"

    def test_manual_same_day_scope_preserves_daily_work_without_adopting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            current = root / "occurrences" / self.CURRENT
            categories = write_reset_occurrence_state(current, self.CURRENT)
            raw = (current / "family-progress.json").read_bytes()
            request = "one-extra-family"
            key = hashlib.sha256(request.encode()).hexdigest()
            # The peer's independent replay is covered by the native verifier;
            # this test isolates occurrence selection from its legacy toy EXP data.
            with patch.object(delivery, "_load_family_progress", return_value=categories) as replay:
                selected, reset, completed = delivery._select_family_state(root, self.CURRENT,
                    operator_request_id=request)
                self.assertEqual(replay.call_count, 1)
            self.assertEqual((selected, reset, completed),
                (root / "manual-runs" / key / "occurrences" / self.CURRENT, self.CURRENT, {}))
            self.assertFalse(selected.exists())
            self.assertEqual((current / "family-progress.json").read_bytes(), raw)

    def test_unresolved_manual_scope_blocks_normal_and_new_manual_family(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            write_reset_occurrence_state(root / "manual-runs" / ("a" * 64) / "occurrences" / self.CURRENT,
                        self.CURRENT, pending=True)
            for request in (None, "another-extra-family"):
                with self.subTest(request=request), self.assertRaises(pnsctl.OperatorError):
                    delivery._select_family_state(root, self.CURRENT, operator_request_id=request)

    def test_only_explicit_manual_daily_claim_ignores_daily_due(self):
        for cadence, mode, permit, expected in (
            ("daily_once_per_reset", "manual", False, False),
            ("daily_once_per_reset", "manual", True, True),
            ("daily_once_per_reset", "scheduled", True, False),
            ("cooldown_pulse", "manual", True, False),
        ):
            with self.subTest(cadence=cadence, mode=mode, permit=permit), tempfile.TemporaryDirectory() as folder:
                with BotStateManager(Path(folder) / "state.sqlite3") as state:
                    state.initialize_flows([FlowSpec("daily", cadence=cadence)])
                    state.set_service_enabled(True, now_utc_epoch=100)
                    state.set_flow_enabled("daily", True, now_utc_epoch=100)
                    state.update_schedule("daily", next_due_at_utc=200, next_occurrence_key=1,
                                          now_utc_epoch=100)
                    run = state.claim_occurrence("daily", "game-day-2026-11-01", mode=mode,
                        operator_request_id="explicit-extra", allow_completed_daily=permit,
                        now_utc_epoch=101)
                    self.assertEqual(run is not None, expected)
                    flow = state.get_flow("daily")
                    self.assertEqual((flow.next_due_at_utc, flow.next_occurrence_key), (200, 1))
                    if run:
                        self.assertEqual((run.mode, run.occurrence_basis), ("manual", "explicit-extra"))


if __name__ == "__main__":
    unittest.main()
