"""Focused tests for the BlueStacks Daily Row flow-delivery adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

import scripts.pnsctl as pnsctl
import scripts.flow_delivery_daily_row_claim_bluestacks as delivery
import scripts.navigation_development_boundary as boundary
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)
from scripts.flow_delivery_daily_row_claim_bluestacks import (
    FLOW_ID,
    MAX_INPUTS,
    RUNNER_ID,
    _write_delivery_result,
    _max_inputs,
    run_daily_row_claim,
)


class DailyRowClaimFlowDeliveryTests(unittest.TestCase):
    def _lease(self, *, maximum: int = MAX_INPUTS):
        return {
            "owner": "outer-development-session",
            "max_inputs": maximum,
            "development_session": SimpleNamespace(
                session_directory=Path("tests") / "daily-row-claim-dry-run-session",
                run_action=lambda **_kwargs: None,
            ),
        }

    def test_registry_binds_consequential_runner_without_promotion(self):
        contract = pnsctl._load_bluestacks_flow_registry()[FLOW_ID]
        self.assertEqual(contract["runner"], RUNNER_ID)
        self.assertEqual(contract["consequence_class"], "consequential")
        self.assertIn(RUNNER_ID, pnsctl._BLUESTACKS_FLOW_RUNNERS)
        self.assertEqual(
            contract["recovery_handler"],
            "daily_row_claim_bluestacks_recovery",
        )

    def test_dry_run_is_zero_transport_and_preserves_disabled_state(self):
        result = run_daily_row_claim(
            {"active_flow_id": FLOW_ID},
            self._lease(),
            live=False,
        )
        self.assertIn('"status": "dry_run"', result)
        self.assertIn('"input_count": 0', result)
        self.assertIn('"dispatch": false', result)
        self.assertIn('"production_registration": "NOT_REGISTERED"', result)
        self.assertIn('"scheduler_enabled": false', result)

    def test_max_inputs_is_bounded_at_reconnaissance_plus_canary_ceiling(self):
        self.assertEqual(_max_inputs(self._lease(maximum=MAX_INPUTS)), MAX_INPUTS)
        with self.assertRaises(pnsctl.OperatorError):
            _max_inputs(self._lease(maximum=MAX_INPUTS + 1))
        with self.assertRaises(pnsctl.OperatorError):
            _max_inputs(self._lease(maximum=0))

    def test_live_admission_rejects_missing_fabricated_inactive_or_unbound_session(self):
        fabricated = SimpleNamespace(
            owner=f"pnsctl-development-session:{FLOW_ID}",
            is_active=True,
            run_action=lambda **_kwargs: None,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(delivery.LocalBlueStacksRuntime, "connect") as connect:
                for label, lease in (
                    ("missing", {}),
                    ("fabricated", {"development_session": fabricated}),
                    (
                        "inactive",
                        {
                            "development_session": DevelopmentSession(
                                owner=f"pnsctl-development-session:{FLOW_ID}",
                                invocation_id="inactive",
                                session_directory=root / "inactive",
                                max_inputs=MAX_INPUTS,
                            )
                        },
                    ),
                ):
                    with self.subTest(label=label), self.assertRaises(pnsctl.OperatorError):
                        run_daily_row_claim({}, {**lease, "max_inputs": MAX_INPUTS}, live=True)
                connect.assert_not_called()

            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{FLOW_ID}",
                    invocation_id="bound",
                    session_directory=root / "bound",
                    max_inputs=MAX_INPUTS,
                ) as session:
                    digest = hashlib.sha256(b"initial").hexdigest()
                    bound = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        invocation_id=session.invocation_id,
                    )
                    session.set_initial_observation(bound)
                    base = {
                        "development_session": session,
                        "initial_frame_sha256": digest,
                        "max_inputs": MAX_INPUTS,
                    }
                    for label, observation in (
                        ("missing-observation", None),
                        (
                            "mismatched-observation",
                            DevelopmentInitialObservation(
                                {"frame_sha256": digest},
                                digest,
                                invocation_id=session.invocation_id,
                            ),
                        ),
                    ):
                        lease = dict(base)
                        if observation is not None:
                            lease["initial_observation"] = observation
                        with self.subTest(label=label), patch.object(
                            delivery.LocalBlueStacksRuntime, "connect"
                        ) as connect:
                            with self.assertRaises(pnsctl.OperatorError):
                                run_daily_row_claim({}, lease, live=True)
                            connect.assert_not_called()

    def test_live_route_binds_exact_initial_observation_and_one_read_only_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "runtime"
            child.mkdir()
            events = [
                {"type": "dispatch", "execute": True, "action_key": "home-quest"},
                {"type": "dispatch", "execute": True, "action_key": "quest-daily"},
                {"type": "dispatch", "execute": True, "action_key": "daily-claim:aggregate"},
                {"type": "dispatch", "execute": True, "action_key": "daily-claim:return-home"},
            ]
            (child / "events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
            )
            initial_bytes = b"typed-initial-frame"
            digest = hashlib.sha256(initial_bytes).hexdigest()
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{FLOW_ID}",
                    invocation_id="daily-continuous",
                    session_directory=root / "outer",
                    max_inputs=MAX_INPUTS,
                ) as session:
                    (session.session_directory / "source.png").write_bytes(initial_bytes)
                    initial = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        frame_path="source.png",
                        invocation_id=session.invocation_id,
                    )
                    session.set_initial_observation(initial)
                    session.adopt_retained_transport_count(MAX_INPUTS, source="test-events")
                    lease = {
                        "owner": session.owner,
                        "max_inputs": MAX_INPUTS,
                        "development_session": session,
                        "initial_observation": initial,
                        "initial_frame_sha256": digest,
                    }
                    with (
                        patch.object(
                            delivery.LocalBlueStacksRuntime,
                            "connect",
                            return_value=SimpleNamespace(session=child),
                        ),
                        patch(
                            "scripts.daily_row_claim_bluestacks.run_daily_row_reconnaissance",
                            return_value={"status": "observed", "game_day_id": "day"},
                        ),
                        patch(
                            "scripts.daily_row_claim_bluestacks.run_daily_row_claim_canary",
                            return_value={
                                "status": "completed",
                                "game_day_id": "day",
                                "claim": {"points_before": 20, "points_after": 25},
                                "recognitions": {
                                    "successor": {
                                        "visual_evidence": {
                                            "selected_daily": True,
                                            "available_ordinary_claim_controls": 0,
                                            "points": 25,
                                        }
                                    }
                                },
                                "home": {"verified": True},
                            },
                        ),
                    ):
                        result = json.loads(run_daily_row_claim({}, lease, live=True))
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(result["proof_topology"], "continuous")
                    self.assertIs(lease["initial_observation"], session.initial_observation)
                    self.assertEqual(result["initial_observation"]["frame_sha256"], digest)
                    self.assertEqual(result["initial_frame_sha256"], digest)
                    self.assertEqual(result["claim_transport_calls"], 1)
                    self.assertEqual(result["causal_trace_count"], 1)
                    self.assertTrue(result["causal_trace"]["read_only"])
                    self.assertFalse(result["causal_trace"]["input_authority"])
                    self.assertEqual(result["causal_trace"]["transport_count"], MAX_INPUTS)
                    self.assertEqual(session.causal_trace, result["causal_trace"])

    def test_completed_artifact_passes_operational_generic_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / ".local-captures" / "daily-row-completed"
            (session / "frames").mkdir(parents=True)
            (session / "frames" / "terminal.png").write_bytes(b"native-frame")
            initial_bytes = b"initial-frame"
            (session / "frames" / "initial.png").write_bytes(initial_bytes)
            initial_digest = hashlib.sha256(initial_bytes).hexdigest()
            events = [
                {"type": "dispatch", "execute": True, "action_key": "home-quest"},
                {"type": "dispatch", "execute": True, "action_key": "quest-daily"},
                {"type": "dispatch", "execute": True, "action_key": "daily-claim:aggregate"},
                {"type": "dispatch", "execute": True, "action_key": "daily-claim:return-home"},
            ]
            (session / "events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
            )
            trace = {
                "trace_count": 1,
                "read_only": True,
                "input_authority": False,
                "proof_topology": "continuous",
                "flow_id": FLOW_ID,
                "initial_frame_sha256": initial_digest,
                "transport_count": 4,
                "claim_transport_calls": 1,
            }
            _write_delivery_result(
                session,
                {
                    "status": "completed",
                    "input_count": 4,
                    "claim_transport_calls": 1,
                    "terminal_home_verified": True,
                    "proof_topology": "continuous",
                    "initial_observation": {
                        "observation": {"frame_sha256": initial_digest},
                        "frame_sha256": initial_digest,
                        "frame_path": "frames/initial.png",
                        "invocation_id": "test-invocation",
                    },
                    "initial_frame_sha256": initial_digest,
                    "causal_trace_count": 1,
                    "causal_trace": trace,
                    "effect_reconciliation_required": False,
                    "canary": {
                        "status": "completed",
                        "claim": {"points_before": 20, "points_after": 25},
                        "recognitions": {
                            "successor": {
                                "visual_evidence": {
                                    "selected_daily": True,
                                    "available_ordinary_claim_controls": 0,
                                    "points": 25,
                                }
                            }
                        },
                        "home": {"verified": True},
                    },
                    "reason": "daily_claim_postcondition_verified",
                },
                lease={"owner": "test-owner"},
                maximum=4,
            )
            with (
                patch.object(pnsctl, "REPO_ROOT", root),
                patch.object(
                    pnsctl,
                    "_load_flow_delivery_state",
                    side_effect=pnsctl.OperatorError("no active delivery"),
                ),
            ):
                verdict = json.loads(pnsctl.bluestacks_verify_flow(session))
            self.assertEqual(verdict["status"], "verified")
            self.assertEqual(verdict["flow_id"], FLOW_ID)
            self.assertTrue(verdict["transport_accounting_verified"])
            self.assertTrue(verdict["semantic_successor_verified"])

            retained = json.loads(
                (session / "flow-delivery-result.json").read_text(encoding="utf-8")
            )
            forged_transport = dict(retained)
            forged_transport["input_count"] = 3
            transport_verdict = delivery.verify_daily_row_claim(
                {"result": forged_transport, "session_directory": str(session)},
                {},
                {},
            )
            self.assertEqual(transport_verdict["status"], "evidence_required")
            self.assertFalse(transport_verdict["transport_accounting_verified"])

            missing_control = json.loads(json.dumps(retained))
            missing_control["canary"]["recognitions"] = {}
            semantic_verdict = delivery.verify_daily_row_claim(
                {"result": missing_control, "session_directory": str(session)},
                {},
                {},
            )
            self.assertEqual(semantic_verdict["status"], "evidence_required")
            self.assertFalse(semantic_verdict["semantic_successor_verified"])


if __name__ == "__main__":
    unittest.main()
