"""Navigation stops must not masquerade as unresolved AP spending."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.flow_delivery_campaign_bluestacks import _campaign_result_payload


class CampaignEffectReportingTests(unittest.TestCase):
    def payload(self, rows, *, input_count=None, campaign=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            return _campaign_result_payload(
                {"status": "blocked", "reason": "unrecognized stage dialog",
                 "campaign_result": campaign or {}},
                session_directory=root,
                input_count=len(rows) if input_count is None else input_count,
                maximum=12, destination="1-15-9", ap_cost=14,
                registration_snapshot={},
            )

    def test_native_pre_challenge_navigation_is_not_an_unresolved_ap_effect(self):
        path = Path(__file__).parent / "fixtures" / "campaign_ap_hud" / "pre-challenge-navigation.json"
        rows = json.loads(path.read_text(encoding="utf-8"))["input_rows"]
        result = self.payload(rows)
        self.assertEqual(result["input_count"], 8)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["dispatch"])
        self.assertTrue(result["navigation_only_trace_verified"])
        self.assertFalse(result["effect_reconciliation_required"])
        self.assertFalse(result["identical_retry_denied"])

    def test_possible_battle_or_unknown_input_still_requires_reconciliation(self):
        for row in (
            {"type": "command", "kind": "tap", "action": "CONFIRM_LINEUP"},
            {"type": "command", "kind": "tap", "action": "UNKNOWN"},
            {"type": "dispatch", "execute": True, "consequential": True,
             "target_identity": "home.building.campaign"},
            {"type": "dispatch", "execute": True, "consequential": False,
             "target_identity": "unknown-purchase"},
        ):
            with self.subTest(row=row):
                result = self.payload([row])
                self.assertTrue(result["effect_reconciliation_required"])
                self.assertTrue(result["identical_retry_denied"])

    def test_missing_or_unaccounted_trace_cannot_prove_no_effect(self):
        result = self.payload([], input_count=1)
        self.assertTrue(result["effect_reconciliation_required"])
        row = {"type": "command", "kind": "tap", "action": "SELECT_TIER",
               "target_identity": "campaign-tier-1"}
        self.assertTrue(self.payload([row], input_count=2)["effect_reconciliation_required"])

    def test_malformed_or_extra_trace_records_do_not_prove_navigation_only(self):
        path = Path(__file__).parent / "fixtures" / "campaign_ap_hud" / "pre-challenge-navigation.json"
        rows = json.loads(path.read_text(encoding="utf-8"))["input_rows"]
        for change in (
            {"execute": None}, {"execute": "false"},
            {"progress": "malformed"},
            {"progress": {"initial_ap": 120, "current_ap": 119,
                          "ap_spent": 0, "completed_runs": 0, "ap_regenerated": 0,
                          "loss_seen": False}},
        ):
            copied = [dict(row) for row in rows]
            copied[-1].update(change)
            with self.subTest(change=change):
                self.assertTrue(self.payload(copied)["effect_reconciliation_required"])
        missing = [dict(row) for row in rows]
        missing[-1].pop("execute")
        self.assertTrue(self.payload(missing)["effect_reconciliation_required"])
        extra = rows + [{"type": "command", "kind": "unknown", "action": "UNKNOWN"}]
        self.assertTrue(self.payload(extra, input_count=len(rows))["effect_reconciliation_required"])

    def test_consumption_evidence_overrides_navigation_labels(self):
        row = {"type": "command", "kind": "tap", "action": "SELECT_TIER",
               "target_identity": "campaign-tier-1", "progress": {"ap_spent": 14}}
        self.assertTrue(self.payload([row])["effect_reconciliation_required"])
        row.pop("progress")
        for campaign in (
            {"ap_before": 120, "ap_after": 106},
            {"ap_after": 106},
            {"progress": {"completed_runs": 1}},
            {"battle_outcome": "victory"},
            {"progress": {"ap_spent": False, "completed_runs": False}},
            {"progress": "malformed"},
            {"progress": None},
        ):
            with self.subTest(campaign=campaign):
                self.assertTrue(self.payload([row], campaign=campaign)["effect_reconciliation_required"])

    def test_completed_result_requires_the_complete_conserved_ap_ledger(self):
        progress = {"initial_ap": 120, "current_ap": 106, "ap_spent": 14,
                    "ap_regenerated": 0, "completed_runs": 1, "loss_seen": False}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "events.jsonl").write_text(
                json.dumps({"type": "command", "kind": "tap", "action": "CONFIRM_LINEUP"}) + "\n",
                encoding="utf-8",
            )
            def report(ledger):
                return _campaign_result_payload(
                    {"status": "completed", "terminal": "completed", "navigation_only": False,
                     "terminal_runtime_state": "recognized_home", "campaign_result": {
                         "destination": "1-15-9", "ap_cost": 14, "ap_before": 120,
                         "ap_after": 106, "battle_outcome": "victory", "progress": ledger}},
                    session_directory=root, input_count=1, maximum=16,
                    destination="1-15-9", ap_cost=14, registration_snapshot={},
                )
            self.assertEqual(report(progress)["status"], "completed")
            for change in (
                {"initial_ap": "bad"}, {"current_ap": -999}, {"ap_regenerated": False},
                {"loss_seen": "unknown"}, {"completed_runs": True}, {"current_ap": 105},
            ):
                with self.subTest(change=change):
                    self.assertEqual(report({**progress, **change})["status"], "effect_reconciliation_required")

    def test_failed_recovery_preserves_the_original_pending_effect_with_zero_new_input(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _campaign_result_payload(
                {"status": "blocked", "victory_home_only": True, "campaign_result": {}},
                session_directory=Path(directory), input_count=0, maximum=16,
                destination="1-15-9", ap_cost=14, registration_snapshot={},
            )
        self.assertEqual(result["status"], "effect_reconciliation_required")
        self.assertTrue(result["identical_retry_denied"])


if __name__ == "__main__":
    unittest.main()
