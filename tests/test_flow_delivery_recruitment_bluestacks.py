"""Focused tests for Recruitment continuous-session flow delivery."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from automation_service.registry import (
    RECRUITMENT_FLOW_ID,
    RECRUITMENT_HANDLER_ID,
    RECRUITMENT_PHASE_MODE,
    RECRUITMENT_PRODUCT_ID,
    RECRUITMENT_PRODUCT_REVISION,
    RECRUITMENT_PROFILE_ID,
    RegisteredDispatchSnapshot,
)
import scripts.flow_delivery_recruitment_bluestacks as delivery
import scripts.navigation_development_boundary as boundary
import scripts.pnsctl as pnsctl
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)


class RecruitmentFlowDeliveryTests(unittest.TestCase):
    def _registration(self) -> RegisteredDispatchSnapshot:
        return RegisteredDispatchSnapshot(
            flow_id=RECRUITMENT_FLOW_ID,
            product_id=RECRUITMENT_PRODUCT_ID,
            product_revision=RECRUITMENT_PRODUCT_REVISION,
            production_handler=RECRUITMENT_HANDLER_ID,
            profile=RECRUITMENT_PROFILE_ID,
            mode=RECRUITMENT_PHASE_MODE,
            registration_status="REGISTERED",
            scheduler_eligible=True,
        )

    def _maintenance_state(self) -> dict:
        return {
            "schema": "noahs-tavern-maintenance-v1",
            "account_id": "account",
            "server_id": "server",
            "reset_id": "reset",
            "basic_daily_count": 1,
            "revision": 3,
            "tiers": {
                "Basic Recruit": {
                    "attempts_remaining": 4,
                    "next_eligible_at": 700.0,
                    "cooldown_seconds": 600,
                    "last_outcome": "action_performed",
                },
                "Int. Recruit": {
                    "attempts_remaining": 1,
                    "next_eligible_at": 86_500.0,
                    "cooldown_seconds": 86_400,
                    "last_outcome": "deferred",
                },
                "Adv. Recruit": {
                    "attempts_remaining": 1,
                    "next_eligible_at": 172_900.0,
                    "cooldown_seconds": 172_800,
                    "last_outcome": "deferred",
                },
            },
        }

    def _events(self, child: Path) -> None:
        events = [
            {
                "type": "dispatch",
                "execute": True,
                "action_key": "noah:open:1",
                "target_identity": "home.building.noahs_tavern",
            },
            {
                "type": "dispatch",
                "execute": True,
                "action_key": "noah:tier:INT:2",
                "target_identity": "NOAHS_TAVERN_TIER_INT",
            },
            {
                "type": "dispatch",
                "execute": True,
                "action_key": "INT:frame:1:None",
                "target_identity": "noahs-tavern-daily-free",
            },
            {
                "type": "dispatch",
                "execute": True,
                "action_key": "INT:frame:1:None:close",
                "target_identity": "noahs-tavern-result-close",
            },
            {
                "type": "dispatch",
                "execute": True,
                "action_key": "noah-nav:safe-exit:3",
                "target_identity": "noahs-tavern-safe-exit",
            },
        ]
        (child / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )

    def _session(self, root: Path):
        digest = hashlib.sha256(b"recruitment-initial").hexdigest()
        with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
            session = DevelopmentSession(
                owner=f"pnsctl-development-session:{delivery.FLOW_ID}",
                invocation_id="recruitment-continuous",
                session_directory=root / "outer",
                max_inputs=delivery.MAX_INPUTS,
            )
            session.__enter__()
        (session.session_directory / "source.png").write_bytes(b"recruitment-initial")
        initial = DevelopmentInitialObservation(
            {"frame_sha256": digest},
            digest,
            frame_path="source.png",
            invocation_id=session.invocation_id,
        )
        session.set_initial_observation(initial)
        return session, initial

    def test_registry_and_dry_run_keep_recruitment_disabled(self):
        contract = pnsctl._load_bluestacks_flow_registry()[delivery.FLOW_ID]
        self.assertEqual(contract["runner"], delivery.RUNNER_ID)
        self.assertEqual(contract["consequence_class"], "consequential")
        self.assertIn(delivery.RUNNER_ID, pnsctl._BLUESTACKS_FLOW_RUNNERS)
        result = json.loads(
            delivery.run_recruitment(
                {}, {"max_inputs": delivery.MAX_INPUTS}, live=False
            )
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["input_count"], 0)
        self.assertEqual(result["recruitment_action_count"], 0)
        self.assertEqual(result["proof_topology"], "continuous")
        self.assertEqual(result["production_registration"], "NOT_REGISTERED")
        self.assertFalse(result["scheduler_enabled"])

    def test_maximum_preserves_full_and_continuation_ceilings(self):
        self.assertEqual(delivery.MAX_INPUTS, 12)
        self.assertEqual(delivery.MAX_CONTINUATION_INPUTS, 4)
        self.assertEqual(delivery._maximum({"max_inputs": 12}), 12)
        with self.assertRaises(pnsctl.OperatorError):
            delivery._maximum({"max_inputs": 13})
        with self.assertRaises(pnsctl.OperatorError):
            delivery._maximum({"max_inputs": 11})
        self.assertEqual(pnsctl._conduct_max_inputs(delivery.FLOW_ID, 12), 12)
        with self.assertRaises(pnsctl.OperatorError):
            pnsctl._conduct_max_inputs(delivery.FLOW_ID, 8)

    def test_live_route_binds_exact_observation_trace_and_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, initial = self._session(root)
            child = root / "outer" / "runtime"
            child.mkdir(parents=True)
            self._events(child)
            lease = {
                "owner": session.owner,
                "development_session": session,
                "initial_observation": initial,
                "initial_frame_sha256": initial.frame_sha256,
                "max_inputs": delivery.MAX_INPUTS,
                "account_id": "account",
                "server_id": "server",
                "reset_id": "reset",
                "registration_snapshot": self._registration(),
            }
            route_result = {
                "status": "completed",
                "reason": "verified_safe_return_home",
                "actions_completed": 1,
                "session_directory": str(child),
                "input_count": 5,
                "terminal_home_verified": True,
                "identity": {
                    "account_id": "account",
                    "server_id": "server",
                    "reset_id": "reset",
                },
                "maintenance_state": self._maintenance_state(),
            }
            try:
                with (
                    patch.object(
                        delivery.LocalBlueStacksRuntime,
                        "connect",
                        return_value=SimpleNamespace(session=child),
                    ),
                    patch(
                        "scripts.noahs_tavern_recruit_bluestacks.run_noahs_tavern_unified_recruitment",
                        return_value=json.dumps(route_result),
                    ),
                ):
                    result = json.loads(delivery.run_recruitment({}, lease, live=True))
                self.assertIs(initial, session.initial_observation)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["input_count"], 5)
                self.assertEqual(result["recruitment_transport_count"], 1)
                self.assertEqual(result["recruitment_action_count"], 1)
                self.assertEqual(result["causal_trace_count"], 1)
                self.assertTrue(result["causal_trace"]["read_only"])
                self.assertFalse(result["causal_trace"]["input_authority"])
                self.assertEqual(result["causal_trace"]["transport_count"], 5)
                self.assertEqual(session.causal_trace, result["causal_trace"])
                verdict = delivery.verify_recruitment(
                    {"result": result, "session_directory": str(child)}, {}, {}
                )
                self.assertEqual(verdict["status"], "verified")
                self.assertTrue(verdict["maintenance_state_verified"])
                forged = json.loads(json.dumps(result))
                forged["maintenance_state"]["tiers"]["Int. Recruit"][
                    "cooldown_seconds"
                ] = 600
                forged_verdict = delivery.verify_recruitment(
                    {"result": forged, "session_directory": str(child)}, {}, {}
                )
                self.assertEqual(forged_verdict["status"], "evidence_required")
            finally:
                session.__exit__(None, None, None)

    def test_dispatch_without_result_successor_requires_reconciliation(self):
        result = delivery._result_payload(
            {
                "status": "completed",
                "actions_completed": 1,
                "terminal_home_verified": False,
            },
            session_directory="runtime",
            input_count=4,
            recruitment_transport_count=1,
            maximum=delivery.MAX_INPUTS,
            registration_snapshot=self._registration().to_mapping(),
        )
        self.assertEqual(result["status"], "effect_reconciliation_required")
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])

    def test_conduct_recruitment_does_not_create_pre_observation_session(self):
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
                        delivery.FLOW_ID,
                        live=True,
                        yes=True,
                        state_root=Path(directory),
                    )
                )
            self.assertEqual(result["flow_id"], delivery.FLOW_ID)
            run_flow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
