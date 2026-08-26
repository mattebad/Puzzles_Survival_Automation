"""Focused tests for Campaign AP continuous-session flow delivery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import scripts.flow_delivery_campaign_bluestacks as delivery
import scripts.navigation_development_boundary as boundary
import scripts.pnsctl as pnsctl
from automation_service.registry import (
    CAMPAIGN_FLOW_ID,
    CAMPAIGN_HANDLER_ID,
    CAMPAIGN_PHASE_MODE,
    CAMPAIGN_PRODUCT_ID,
    CAMPAIGN_PRODUCT_REVISION,
    CAMPAIGN_PROFILE_ID,
    RegisteredDispatchSnapshot,
)
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)


class CampaignFlowDeliveryTests(unittest.TestCase):
    def _registration(self) -> RegisteredDispatchSnapshot:
        return RegisteredDispatchSnapshot(
            CAMPAIGN_FLOW_ID,
            CAMPAIGN_PRODUCT_ID,
            CAMPAIGN_PRODUCT_REVISION,
            CAMPAIGN_HANDLER_ID,
            CAMPAIGN_PROFILE_ID,
            CAMPAIGN_PHASE_MODE,
            "REGISTERED",
            True,
        )

    def _session(self, root: Path):
        digest = hashlib.sha256(b"campaign-initial").hexdigest()
        with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
            session = DevelopmentSession(
                owner=f"pnsctl-development-session:{delivery.AUTO_BATTLE_FLOW_ID}",
                invocation_id="campaign-continuous",
                session_directory=root / "outer",
                max_inputs=delivery.MAX_INPUTS,
            )
            session.__enter__()
        (session.session_directory / "source.png").write_bytes(b"campaign-initial")
        initial = DevelopmentInitialObservation(
            {"frame_sha256": digest},
            digest,
            frame_path="source.png",
            invocation_id=session.invocation_id,
        )
        session.set_initial_observation(initial)
        return session, initial

    def _child_result(self, child: Path, *, ap_after: int = 106) -> None:
        child.mkdir(parents=True, exist_ok=True)
        (child / "frames").mkdir()
        events = [
            {"type": "command", "kind": "tap", "action": "OPEN_CAMPAIGN"},
            {"type": "command", "kind": "swipe", "action": "NAVIGATE_CHAPTER"},
            {"type": "command", "kind": "tap", "action": "ENABLE_AUTO"},
        ]
        (child / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        result = {
            "status": "completed",
            "terminal": "completed",
            "navigation_only": False,
            "battle_outcome": "victory",
            "destination": "1-15-9",
            "ap_before": 120,
            "ap_after": ap_after,
            "ap_cost": 14,
            "progress": {
                "initial_ap": 120,
                "current_ap": ap_after,
                "completed_runs": 1,
                "ap_spent": 14,
                "ap_regenerated": 0,
                "loss_seen": False,
            },
        }
        (child / "result.json").write_text(
            json.dumps(result, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_registry_and_dry_run_keep_campaign_disabled(self):
        contract = pnsctl._load_bluestacks_flow_registry()[delivery.AUTO_BATTLE_FLOW_ID]
        self.assertEqual(contract["runner"], delivery.AUTO_BATTLE_RUNNER_ID)
        self.assertEqual(contract["consequence_class"], "consequential")
        result = json.loads(delivery.run_campaign_auto_battle_live({}, {}, live=False))
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(result["max_inputs"], delivery.MAX_INPUTS)
        self.assertEqual(result["proof_topology"], "continuous")
        self.assertEqual(result["production_registration"], "NOT_REGISTERED")
        self.assertFalse(result["scheduler_enabled"])

    def test_live_route_rejects_sessionless_dispatch(self):
        with self.assertRaisesRegex(
            pnsctl.OperatorError, "active pnsctl-owned DevelopmentSession"
        ):
            delivery.run_campaign_auto_battle_live({}, {}, live=True)

    def test_campaign_requires_exact_continuous_ceiling(self):
        self.assertEqual(delivery._campaign_maximum({"max_inputs": 12}), 12)
        with self.assertRaises(pnsctl.OperatorError):
            delivery._campaign_maximum({"max_inputs": 11})
        self.assertEqual(
            pnsctl._conduct_max_inputs(delivery.AUTO_BATTLE_FLOW_ID, 12),
            12,
        )
        with self.assertRaises(pnsctl.OperatorError):
            pnsctl._conduct_max_inputs(delivery.AUTO_BATTLE_FLOW_ID, 1)

    def test_live_route_binds_session_observation_trace_and_ap_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, initial = self._session(root)
            child = root / "outer" / "runtime" / "1-15-9-run"
            self._child_result(child)
            prep = root / "outer" / "runtime" / "campaign-exit-to-home"
            prep.mkdir()
            (prep / "events.jsonl").write_text(
                json.dumps(
                    {"type": "command", "kind": "tap", "action": "RETURN_HOME"}
                )
                + "\n",
                encoding="utf-8",
            )
            lease = {
                "owner": session.owner,
                "development_session": session,
                "initial_observation": initial,
                "initial_frame_sha256": initial.frame_sha256,
                "max_inputs": delivery.MAX_INPUTS,
                "registration_snapshot": self._registration(),
            }
            process = SimpleNamespace(returncode=0, stdout="", stderr="")
            try:
                with (
                    patch.object(delivery, "_ensure_home_surface_before_prep"),
                    patch.object(delivery.subprocess, "run", return_value=process),
                ):
                    result = json.loads(
                        delivery.run_campaign_auto_battle_live({}, lease, live=True)
                    )
                self.assertIs(initial, session.initial_observation)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["input_count"], 4)
                self.assertEqual(result["campaign_transport_count"], 4)
                self.assertEqual(result["campaign_action_count"], 1)
                self.assertTrue(result["exact_ap_delta"])
                self.assertTrue(result["result_successor_verified"])
                self.assertTrue(result["terminal_home_verified"])
                self.assertTrue(result["refill_forbidden_verified"])
                self.assertEqual(result["production_registration"], "NOT_REGISTERED")
                self.assertFalse(result["scheduler_enabled"])
                self.assertEqual(
                    result["registration_snapshot"],
                    self._registration().to_mapping(),
                )
                self.assertEqual(
                    result["causal_trace"]["registration_snapshot"],
                    result["registration_snapshot"],
                )
                self.assertEqual(result["causal_trace_count"], 1)
                self.assertTrue(result["causal_trace"]["read_only"])
                self.assertFalse(result["causal_trace"]["input_authority"])
                self.assertEqual(session.causal_trace, result["causal_trace"])
                verdict = delivery.verify_campaign_auto_battle_live(
                    {"result": result, "session_directory": str(child)}, {}, {}
                )
                self.assertEqual(verdict["status"], "verified")
                forged = dict(result)
                forged["registration_snapshot"] = dict(result["registration_snapshot"])
                forged["registration_snapshot"]["flow_id"] = (
                    "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE"
                )
                forged_verdict = delivery.verify_campaign_auto_battle_live(
                    {"result": forged, "session_directory": str(child)}, {}, {}
                )
                self.assertEqual(forged_verdict["status"], "evidence_required")
                self.assertFalse(forged_verdict["registration_verified"])
            finally:
                session.__exit__(None, None, None)

    def test_dispatch_without_exact_ap_successor_requires_reconciliation(self):
        result = delivery._campaign_result_payload(
            {
                "status": "completed",
                "terminal": "completed",
                "navigation_only": False,
                "terminal_runtime_state": "recognized_home",
                "campaign_result": {
                    "ap_before": 120,
                    "ap_after": 107,
                    "battle_outcome": "victory",
                    "progress": {"completed_runs": 1},
                },
            },
            session_directory=Path("runtime"),
            input_count=3,
            maximum=delivery.MAX_INPUTS,
            destination="1-15-9",
            ap_cost=14,
            registration_snapshot=self._registration().to_mapping(),
        )
        self.assertEqual(result["status"], "effect_reconciliation_required")
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])

    def test_refill_marker_and_forged_registration_cannot_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "events.jsonl").write_text(
                json.dumps(
                    {"type": "command", "kind": "tap", "action": "AP_REFILL"}
                )
                + "\n",
                encoding="utf-8",
            )
            result = delivery._campaign_result_payload(
                {
                    "status": "completed",
                    "terminal": "completed",
                    "navigation_only": False,
                    "terminal_runtime_state": "recognized_home",
                    "campaign_result": {
                        "destination": "1-15-9",
                        "ap_cost": 14,
                        "ap_before": 120,
                        "ap_after": 106,
                        "battle_outcome": "victory",
                        "progress": {"completed_runs": 1, "ap_spent": 14},
                    },
                },
                session_directory=root,
                input_count=1,
                maximum=delivery.MAX_INPUTS,
                destination="1-15-9",
                ap_cost=14,
                registration_snapshot=self._registration().to_mapping(),
            )
            self.assertFalse(result["refill_forbidden_verified"])
            self.assertEqual(result["status"], "effect_reconciliation_required")

    def test_live_route_rejects_missing_registration_before_session(self):
        with self.assertRaisesRegex(pnsctl.OperatorError, "typed registration snapshot"):
            delivery._run_campaign_auto_battle_continuous(
                {},
                {"max_inputs": delivery.MAX_INPUTS},
            )

    def test_conduct_campaign_does_not_create_pre_observation_session(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(
                    pnsctl,
                    "development_session_observe",
                    side_effect=AssertionError("pre-observation is forbidden"),
                ),
                patch.object(
                    pnsctl,
                    "development_session_run_flow",
                    return_value=json.dumps({"status": "blocked"}),
                ) as run_flow,
            ):
                result = json.loads(
                    pnsctl.conduct_flow(
                        delivery.AUTO_BATTLE_FLOW_ID,
                        live=True,
                        yes=True,
                        state_root=Path(directory),
                    )
                )
            self.assertEqual(result["flow_id"], delivery.AUTO_BATTLE_FLOW_ID)
            run_flow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
