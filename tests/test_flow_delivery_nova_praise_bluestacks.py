"""Focused tests for the fixed Nova development-session binding."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scripts.pnsctl as pnsctl
from scripts.flow_delivery_nova_praise_bluestacks import (
    FLOW_ID,
    MAX_INPUTS,
    MAX_PRAISE,
    RUNNER_ID,
    _identity,
    _max_inputs,
    run_nova_praise_supervised_one_free_pulse,
)


class NovaFlowDeliveryBindingTests(unittest.TestCase):
    def _identity(self, reset_id: str = "game-day-2026-08-18"):
        return SimpleNamespace(
            runtime_scope="bluestacks-dev-primary",
            account_id="acct-1",
            server_id="server-1",
            reset_id=reset_id,
        )

    def _lease(self, *, maximum: int = 8, reset_id: str = "game-day-2026-08-18"):
        identity = self._identity(reset_id)
        return {
            "owner": "outer-development-session",
            "max_inputs": maximum,
            "nova_identity": identity,
            "nova_reset_id": reset_id,
            "development_session": object(),
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


if __name__ == "__main__":
    unittest.main()
