"""Focused tests for the fixed Nova development-session binding."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scripts.pnsctl as pnsctl
import scripts.flow_delivery_nova_praise_bluestacks as delivery
import scripts.navigation_development_boundary as boundary
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)
from automation_service.registry import (
    NOVA_FLOW_ID,
    NOVA_HANDLER_ID,
    NOVA_PHASE_MODE,
    NOVA_PRODUCT_ID,
    NOVA_PRODUCT_REVISION,
    NOVA_PROFILE_ID,
    RegisteredDispatchSnapshot,
)
from scripts.flow_delivery_nova_praise_bluestacks import (
    FLOW_ID,
    MAX_INPUTS,
    MAX_PRAISE,
    RUNNER_ID,
    _write_delivery_result,
    _identity,
    _max_inputs,
    run_nova_praise_supervised_one_free_pulse,
    verify_nova_praise_supervised_one_free_pulse,
)


class NovaFlowDeliveryBindingTests(unittest.TestCase):
    def _identity(self, reset_id: str = "game-day-2026-08-18"):
        return SimpleNamespace(
            runtime_scope="bluestacks-dev-primary",
            account_id="acct-1",
            server_id="server-1",
            reset_id=reset_id,
        )

    def _registration_snapshot(self) -> RegisteredDispatchSnapshot:
        return RegisteredDispatchSnapshot(
            NOVA_FLOW_ID,
            NOVA_PRODUCT_ID,
            NOVA_PRODUCT_REVISION,
            NOVA_HANDLER_ID,
            NOVA_PROFILE_ID,
            NOVA_PHASE_MODE,
            "REGISTERED",
            True,
        )

    def _lease(self, *, maximum: int = 8, reset_id: str = "game-day-2026-08-18"):
        identity = self._identity(reset_id)
        return {
            "owner": "outer-development-session",
            "max_inputs": maximum,
            "nova_identity": identity,
            "nova_reset_id": reset_id,
            "development_session": object(),
            "registration_snapshot": self._registration_snapshot(),
        }

    def test_registry_binds_fixed_runner_without_production_promotion(self) -> None:
        contract = pnsctl._load_bluestacks_flow_registry()[FLOW_ID]
        self.assertEqual(contract["runner"], RUNNER_ID)
        self.assertEqual(contract["consequence_class"], "consequential")
        self.assertIn(RUNNER_ID, pnsctl._BLUESTACKS_FLOW_RUNNERS)
        self.assertEqual(contract["recovery_handler"], "nova_praise_supervised_one_free_pulse_recovery")

    def test_dry_run_requires_verified_identity_and_preserves_disabled_state(self) -> None:
        result = run_nova_praise_supervised_one_free_pulse(
            {},
            self._lease(maximum=8),
            live=False,
        )
        self.assertIn('"status": "dry_run"', result)
        self.assertIn('"max_inputs": 8', result)
        self.assertIn('"production_registration": "NOT_REGISTERED"', result)
        self.assertIn('"scheduler_enabled": false', result)

    def test_max_inputs_and_reset_binding_fail_closed(self) -> None:
        with self.assertRaises(pnsctl.OperatorError):
            _max_inputs(self._lease(maximum=MAX_INPUTS + 1))
        with self.assertRaises(pnsctl.OperatorError):
            _identity({**self._lease(), "nova_reset_id": "other-reset"})
        with self.assertRaises(pnsctl.OperatorError):
            _identity({**self._lease(), "nova_reset_id": "../escape"})

    def test_identity_cli_arguments_are_run_flow_specific(self) -> None:
        args = pnsctl.parser().parse_args(
            [
                "development-session",
                "run-flow",
                FLOW_ID,
                "--runtime-scope",
                "bluestacks-dev-primary",
                "--account-id",
                "acct-1",
                "--server-id",
                "server-1",
                "--reset-id",
                "game-day-2026-08-18",
                "--identity-evidence",
                "identity.json",
            ]
        )
        self.assertEqual(args.flow_id, FLOW_ID)
        self.assertEqual(args.max_inputs, 12)
        self.assertEqual(args.reset_id, "game-day-2026-08-18")

    def test_one_praise_ceiling_is_frozen(self) -> None:
        self.assertEqual(MAX_PRAISE, 1)
        self.assertEqual(pnsctl.NOVA_SUPERVISED_PRAISE_MAX_INPUTS, 1)

    def test_reset_scoped_guard_lifecycle_preserves_prior_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(pnsctl, "REPO_ROOT", root):
                with patch.object(
                    pnsctl,
                    "NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT",
                    root / ".local-captures" / FLOW_ID,
                ):
                    first = pnsctl._create_nova_supervised_invocation_guard(
                        candidate_commit="a" * 40,
                        reset_id="game-day-2026-08-17",
                    )
                    second = pnsctl._create_nova_supervised_invocation_guard(
                        candidate_commit="b" * 40,
                        reset_id="game-day-2026-08-18",
                    )
                    first_before = first.read_text(encoding="utf-8")
                    session = (
                        root
                        / ".local-captures"
                        / FLOW_ID
                        / "nova-praise-one-free-pulse-20260818T000000Z"
                    )
                    session.mkdir(parents=True)
                    pnsctl._bind_nova_supervised_invocation_guard_session(
                        str(session),
                        reset_id="game-day-2026-08-18",
                    )
                    pnsctl._finalize_nova_supervised_invocation_guard(
                        terminal_status="blocked",
                        result_status="blocked",
                        session_directory=str(session),
                        reset_id="game-day-2026-08-18",
                    )
                    self.assertNotEqual(first, second)
                    self.assertEqual(first.read_text(encoding="utf-8"), first_before)
                    self.assertEqual(
                        json.loads(second.read_text(encoding="utf-8"))["reset_id"],
                        "game-day-2026-08-18",
                    )
                    with self.assertRaises(pnsctl.OperatorError):
                        pnsctl._create_nova_supervised_invocation_guard(
                            candidate_commit="c" * 40,
                            reset_id="game-day-2026-08-18",
                        )
                    with self.assertRaises(pnsctl.OperatorError):
                        pnsctl._bind_nova_supervised_invocation_guard_session(
                            str(session),
                            reset_id="../escape",
                        )

    def test_live_admission_requires_exact_active_session_observation(self) -> None:
        fabricated = SimpleNamespace(
            owner=f"pnsctl-development-session:{FLOW_ID}",
            is_active=True,
            run_action=lambda **_kwargs: None,
        )
        with patch.object(delivery, "_candidate_commit") as candidate:
            for label, session in (("missing", None), ("fabricated", fabricated)):
                lease = self._lease()
                lease["development_session"] = session
                with self.subTest(label=label), self.assertRaises(pnsctl.OperatorError):
                    run_nova_praise_supervised_one_free_pulse({}, lease, live=True)
            candidate.assert_not_called()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{FLOW_ID}",
                    invocation_id="nova-bound",
                    session_directory=root / "outer",
                    max_inputs=MAX_INPUTS,
                ) as session:
                    digest = hashlib.sha256(b"initial").hexdigest()
                    bound = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        invocation_id=session.invocation_id,
                    )
                    session.set_initial_observation(bound)
                    lease = {
                        **self._lease(),
                        "owner": session.owner,
                        "development_session": session,
                        "initial_frame_sha256": digest,
                        "initial_observation": DevelopmentInitialObservation(
                            {"frame_sha256": digest},
                            digest,
                            invocation_id=session.invocation_id,
                        ),
                    }
                    lease.pop("registration_snapshot")
                    with patch.object(delivery, "_candidate_commit") as candidate:
                        with self.assertRaises(pnsctl.OperatorError):
                            run_nova_praise_supervised_one_free_pulse({}, lease, live=True)
                        candidate.assert_not_called()

    def _route_result(self, session: Path, **overrides) -> dict:
        payload = {
            "schema_version": 1,
            "status": "completed",
            "reason": "confirmed_praise_and_verified_safe_return_home",
            "session_directory": str(session),
            "navigation_input_count": 4,
            "praise_transport_calls": 1,
            "attempts_before": 6,
            "attempts_after": 5,
            "cooldown_seconds": 300,
            "action_id": "nova-action",
            "action_key": "nova-praise:key",
            "journal_status": "confirmed",
            "evidence_refs": ["frames/post.png"],
            "terminal_home_verified": True,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
        payload.update(overrides)
        return payload

    def _write_events(self, session: Path) -> None:
        rows = [
            {"type": "dispatch", "execute": True, "action_key": f"navigation-{index}"}
            for index in range(4)
        ]
        rows.append(
            {
                "type": "dispatch",
                "execute": True,
                "consequential": True,
                "action_key": "nova-praise:key",
            }
        )
        (session / "events.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def test_live_route_binds_initial_observation_trace_and_exact_transports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "runtime"
            (child / "frames").mkdir(parents=True)
            (child / "frames" / "post.png").write_bytes(b"post")
            self._write_events(child)
            initial_bytes = b"typed-nova-initial"
            digest = hashlib.sha256(initial_bytes).hexdigest()
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{FLOW_ID}",
                    invocation_id="nova-continuous",
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
                    lease = {
                        **self._lease(),
                        "owner": session.owner,
                        "development_session": session,
                        "initial_observation": initial,
                        "initial_frame_sha256": digest,
                    }
                    route_result = self._route_result(child)
                    with (
                        patch.object(delivery, "_candidate_commit", return_value="a" * 40),
                        patch.object(pnsctl, "_create_nova_supervised_invocation_guard"),
                        patch.object(pnsctl, "_bind_nova_supervised_invocation_guard_session"),
                        patch.object(pnsctl, "_finalize_nova_supervised_invocation_guard"),
                        patch.object(pnsctl, "_persist_nova_session_result", return_value={}),
                        patch(
                            "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                            return_value=json.dumps(route_result),
                        ),
                    ):
                        result = json.loads(
                            run_nova_praise_supervised_one_free_pulse({}, lease, live=True)
                        )
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(result["proof_topology"], "continuous")
                    self.assertIs(initial, session.initial_observation)
                    self.assertEqual(result["initial_frame_sha256"], digest)
                    self.assertEqual(result["causal_trace_count"], 1)
                    self.assertTrue(result["causal_trace"]["read_only"])
                    self.assertFalse(result["causal_trace"]["input_authority"])
                    self.assertEqual(result["causal_trace"]["transport_count"], 5)
                    self.assertEqual(result["praise_transport_calls"], 1)
                    self.assertEqual(session.causal_trace, result["causal_trace"])

    def test_dispatch_bearing_unknown_requires_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "runtime"
            (child / "frames").mkdir(parents=True)
            (child / "frames" / "post.png").write_bytes(b"post")
            self._write_events(child)
            initial_bytes = b"unknown-initial"
            digest = hashlib.sha256(initial_bytes).hexdigest()
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{FLOW_ID}",
                    invocation_id="nova-unknown",
                    session_directory=root / "outer",
                    max_inputs=MAX_INPUTS,
                ) as session:
                    (session.session_directory / "source.png").write_bytes(initial_bytes)
                    initial = DevelopmentInitialObservation(
                        {"frame_sha256": digest}, digest, invocation_id=session.invocation_id
                    )
                    session.set_initial_observation(initial)
                    lease = {
                        **self._lease(),
                        "owner": session.owner,
                        "development_session": session,
                        "initial_observation": initial,
                        "initial_frame_sha256": digest,
                    }
                    route_result = self._route_result(
                        child,
                        status="unresolved",
                        journal_status="pending_reconciliation",
                        terminal_home_verified=False,
                    )
                    with (
                        patch.object(delivery, "_candidate_commit", return_value="a" * 40),
                        patch.object(pnsctl, "_create_nova_supervised_invocation_guard"),
                        patch.object(pnsctl, "_bind_nova_supervised_invocation_guard_session"),
                        patch.object(pnsctl, "_finalize_nova_supervised_invocation_guard"),
                        patch.object(pnsctl, "_persist_nova_session_result", return_value={}),
                        patch(
                            "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                            return_value=json.dumps(route_result),
                        ),
                    ):
                        result = json.loads(
                            run_nova_praise_supervised_one_free_pulse({}, lease, live=True)
                        )
                    self.assertEqual(result["status"], "effect_reconciliation_required")
                    self.assertTrue(result["effect_reconciliation_required"])
                    self.assertTrue(result["scenario_record"]["unresolved_action"])

    def test_checked_in_verifier_recounts_transport_and_semantic_successor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            (session / "frames").mkdir()
            initial_bytes = b"verified-initial"
            (session / "frames" / "initial.png").write_bytes(initial_bytes)
            (session / "frames" / "post.png").write_bytes(b"post")
            digest = hashlib.sha256(initial_bytes).hexdigest()
            self._write_events(session)
            trace = {
                "trace_count": 1,
                "read_only": True,
                "input_authority": False,
                "scheduler_enabled": False,
                "proof_topology": "continuous",
                "initial_frame_sha256": digest,
                "transport_count": 5,
                "praise_transport_calls": 1,
            }
            trace["registration_snapshot"] = self._registration_snapshot().to_mapping()
            trace["dispatch_registration"] = dict(trace["registration_snapshot"])
            result = {
                **self._route_result(session),
                "input_count": 5,
                "proof_topology": "continuous",
                "initial_observation": {
                    "frame_sha256": digest,
                    "frame_path": "frames/initial.png",
                    "invocation_id": "verified-invocation",
                },
                "initial_frame_sha256": digest,
                "causal_trace_count": 1,
                "causal_trace": trace,
                "effect_reconciliation_required": False,
            }
            result["production_registration"] = "REGISTERED"
            result["scheduler_enabled"] = False
            result["registration_snapshot"] = self._registration_snapshot().to_mapping()
            result["dispatch_registration"] = dict(result["registration_snapshot"])
            _write_delivery_result(
                session,
                result,
                lease={"owner": "test-owner"},
                maximum=MAX_INPUTS,
                candidate_commit="a" * 40,
            )
            retained = json.loads(
                (session / "flow-delivery-result.json").read_text(encoding="utf-8")
            )
            verdict = verify_nova_praise_supervised_one_free_pulse(
                {"result": retained, "session_directory": str(session)}, {}, {}
            )
            self.assertEqual(verdict["status"], "verified")
            self.assertTrue(verdict["transport_accounting_verified"])
            self.assertTrue(verdict["semantic_successor_verified"])

            forged = dict(retained)
            forged["input_count"] = 4
            verdict = verify_nova_praise_supervised_one_free_pulse(
                {"result": forged, "session_directory": str(session)}, {}, {}
            )
            self.assertEqual(verdict["status"], "evidence_required")
            self.assertFalse(verdict["transport_accounting_verified"])

            forged_registration = dict(retained)
            forged_registration["registration_snapshot"] = {
                **retained["registration_snapshot"],
                "product_id": "world_map_navigation",
            }
            verdict = verify_nova_praise_supervised_one_free_pulse(
                {"result": forged_registration, "session_directory": str(session)}, {}, {}
            )
            self.assertEqual(verdict["status"], "evidence_required")
            self.assertFalse(verdict["registration_verified"])

            missing_successor = dict(retained)
            missing_successor["attempts_after"] = retained["attempts_before"]
            verdict = verify_nova_praise_supervised_one_free_pulse(
                {"result": missing_successor, "session_directory": str(session)}, {}, {}
            )
            self.assertEqual(verdict["status"], "evidence_required")
            self.assertFalse(verdict["semantic_successor_verified"])


if __name__ == "__main__":
    unittest.main()
