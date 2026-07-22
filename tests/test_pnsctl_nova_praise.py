"""Focused pnsctl admission tests for Nova navigation and supervised one-free-pulse."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.pnsctl as pnsctl
from scripts import navigation_development_boundary as nav_boundary
from tasks.nova_praise_pulse import NOVA_TASK_ID


def _valid_supervised_result(**overrides) -> dict:
    payload = {
        "schema_version": 1,
        "flow_id": pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID,
        "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
        "status": "completed",
        "reason": "confirmed_praise_and_verified_safe_return_home",
        "navigation_input_count": 4,
        "praise_transport_calls": 1,
        "praise_taps": 1,
        "attempts_before": 6,
        "attempts_after": 5,
        "cooldown_seconds": 278,
        "next_eligible_at": 400.0,
        "action_id": "nova-praise-action",
        "action_key": "nova-praise:key",
        "journal_status": "confirmed",
        "scheduler_outcome": "ACTION_PERFORMED",
        "evidence_refs": ["praise-central-immediate-before.png", "praise-central-post-1.png"],
        "terminal_home_verified": True,
        "action_database": str(pnsctl.NOVA_SUPERVISED_ACTION_DATABASE),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
        "events_path": "events.jsonl",
        "ledger_path": "ledger.jsonl",
        "journal_path": "journal.jsonl",
        "candidate_commit": "a" * 40,
        "scenario_record": {
            "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
            "phase": "execution",
            "outcome": "completed",
            "candidate_commit": "a" * 40,
            "navigation_input_count": 4,
            "praise_transport_calls": 1,
            "input_class": "mixed_navigation_and_one_consequential",
            "consumes_execution_budget": True,
            "reason": "confirmed_praise_and_verified_safe_return_home",
            "failure_class": None,
            "terminal_ownership_state": "released",
            "unresolved_action": False,
            "evidence_refs": ["session"],
            "input_count": 5,
        },
    }
    payload.update(overrides)
    return payload


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _seed_action_database(path: Path, *, action_id: str, action_key: str) -> None:
    from safe_action_core import SafetyStore

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    store = SafetyStore(path)
    try:
        store.connection.execute(
            """
            INSERT INTO actions (
                action_id, action_key, task_id, semantic_action, source_state,
                target_identity, target_roi_json, source_frame_sha256,
                source_frame_captured_at, runtime_profile_id, game_day_id,
                expected_postcondition, consequence, cost_type, cost_amount,
                quantity, consequential, policy_request_json, policy_decision,
                policy_reason, prepared_at, input_attempt_at, transport_result_json,
                reconciliation_result_json, evidence_refs_json, final_status,
                final_reason, updated_at
            ) VALUES (
                ?, ?, ?, 'praise', 'nova_lab', 'nova', '[]', 'abc', 1.0, 'profile',
                'game-day-2026-07-22', 'decrement', 'praise', 'none', 0, 1, 1, '{}',
                'allow', 'ok', 1.0, 2.0, '{}', '{}', '[]', 'confirmed', 'ok', 3.0
            )
            """,
            (action_id, action_key, NOVA_TASK_ID),
        )
        store.connection.commit()
    finally:
        store.close()


def _write_realistic_session(root: Path, result: dict) -> Path:
    captures = root / ".local-captures" / "flow-delivery" / pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID
    session = captures / "session-1"
    session.mkdir(parents=True)
    for name in result.get("evidence_refs") or []:
        (session / str(name)).write_bytes(b"png-bytes")
    action_id = str(result["action_id"])
    action_key = str(result["action_key"])
    _write_jsonl(
        session / "events.jsonl",
        [
            {"type": "navigation", "action": "open_lab"},
            {
                "type": "dispatch",
                "consequential": True,
                "action_key": action_key,
                "action_id": action_id,
            },
        ],
    )
    _write_jsonl(
        session / "ledger.jsonl",
        [{"action": "navigation", "authorized": True}, {"action": "praise", "authorized": True}],
    )
    _write_jsonl(
        session / "journal.jsonl",
        [
            {
                "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                "action_id": action_id,
                "action_key": action_key,
                "journal_status": result.get("journal_status"),
                "attempts_before": result.get("attempts_before"),
                "attempts_after": result.get("attempts_after"),
                "cooldown_seconds": result.get("cooldown_seconds"),
                "terminal_home_verified": result.get("terminal_home_verified"),
            }
        ],
    )
    db_path = Path(str(result["action_database"]))
    _seed_action_database(db_path, action_id=action_id, action_key=action_key)
    (session / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return session


def _live_attempt(head: str) -> dict:
    return {
        "ordinal": 1,
        "active_flow": pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID,
        "lease_owner": "parent-owner",
        "lease_session": "parent-session",
        "repository_head": head,
        "started_at": "2026-07-22T00:00:00Z",
        "finished_at": None,
        "session_directory": None,
        "terminal_outcome": None,
        "diagnosis": "initial authorized attempt",
    }


def _queue_flow(*, attempts: list | None = None, count: int | None = None) -> dict:
    live_attempts = list(attempts or [])
    live_count = len(live_attempts) if count is None else count
    return {
        "queue_kind": "development_flow_delivery",
        "active_flow_id": pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID,
        "flows": [
            {
                "flow_id": pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID,
                "status": "active",
                "product_policy_status": "supervised_consequential_validation",
                "maximum_live_attempts": 1,
                "live_attempt_count": live_count,
                "live_attempts": live_attempts,
            }
        ],
    }


def _lease(*, stage: str) -> dict:
    return {
        "workflow": "pns-flow-delivery",
        "active_flow": pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID,
        "active_stage": stage,
        "runtime_ownership_state": "held",
        "unresolved_action_state": "clear",
        "owner": "parent-owner",
        "process_or_session_identity": "parent-session",
    }


class PnsctlNovaPraiseAdmissionTests(unittest.TestCase):
    def _identity_args(self, evidence: Path, *, scenario: str, extra: list[str] | None = None) -> list[str]:
        args = [
            "nova-praise-pulse",
            "--live",
            "--yes",
            "--supervised-live-opt-in",
            "--scenario",
            scenario,
            "--runtime-scope",
            "bluestacks-dev-primary",
            "--account-id",
            "acct-1",
            "--server-id",
            "server-1",
            "--reset-id",
            "game-day-2026-07-22",
            "--identity-evidence",
            str(evidence),
        ]
        if extra:
            args.extend(extra)
        return args

    def _write_identity(self, directory: Path, *, reset_id: str = "game-day-2026-07-22") -> Path:
        evidence = directory / "identity.json"
        evidence.write_text(
            json.dumps(
                {
                    "account_id": "acct-1",
                    "server_id": "server-1",
                    "reset_id": reset_id,
                    "assurance": "supervised_navigation_binding",
                    "evidence_refs": ["operator-bound-current-frame"],
                }
            ),
            encoding="utf-8",
        )
        return evidence

    def _patch_repo_paths(self, root: Path):
        orchestrator = root / ".local-orchestrator"
        orchestrator.mkdir(parents=True, exist_ok=True)
        action_db = orchestrator / "bluestacks-actions.sqlite3"
        lock_path = orchestrator / "bluestacks-runtime-input-lock.sqlite3"
        guard = (
            orchestrator / "nova-praise-one-free-pulse-game-day-2026-07-22.guard.json"
        )
        output = (
            root / ".local-captures" / "flow-delivery" / pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID
        )
        return (
            patch.object(pnsctl, "REPO_ROOT", root),
            patch.object(pnsctl, "NOVA_SUPERVISED_ACTION_DATABASE", action_db),
            patch.object(pnsctl, "NOVA_SUPERVISED_INVOCATION_GUARD", guard),
            patch.object(pnsctl, "NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT", output),
            patch.object(
                pnsctl,
                "NOVA_NAVIGATION_CANARY_OUTPUT_DEFAULT",
                root / ".local-captures" / "flow-delivery" / "NOVA-PRAISE-HOME-ATLAS-MIGRATION",
            ),
            patch.object(pnsctl, "FLOW_DELIVERY_QUEUE", root / "queue.json"),
            patch.object(pnsctl, "FLOW_DELIVERY_LEASE", root / "lease.json"),
            patch.object(nav_boundary, "RUNTIME_INPUT_LOCK_PATH", lock_path),
            patch.object(nav_boundary, "CANONICAL_ACTION_STORE_PATH", action_db),
            patch.object(nav_boundary, "ORCHESTRATOR_DIR", orchestrator),
        )

    def _enter_patches(self, patches):
        return patches  # caller uses nested with; helper documents length

    def _bind_supervised_args(self, args, root: Path, *, head: str = "a" * 40):
        args.output_directory = pnsctl.NOVA_NAVIGATION_CANARY_OUTPUT_DEFAULT
        args.action_database = pnsctl.NOVA_SUPERVISED_ACTION_DATABASE
        return patch(
            "subprocess.run",
            return_value=type("Proc", (), {"stdout": head + "\n", "returncode": 0})(),
        )

    def test_no_praise_scenario_keeps_canary_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            args = pnsctl.parser().parse_args(
                self._identity_args(evidence, scenario="nova_navigation_round_trip_no_praise")
            )
            self.assertEqual(args.output_directory, pnsctl.NOVA_NAVIGATION_CANARY_OUTPUT_DEFAULT)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                with patch(
                    "subprocess.run",
                    return_value=type("Proc", (), {"stdout": "a" * 40 + "\n", "returncode": 0})(),
                ):
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_navigation_canary",
                        return_value=json.dumps(
                            {
                                "status": "completed",
                                "scenario_id": "nova_navigation_round_trip_no_praise",
                                "transport_calls": 3,
                                "navigation_input_count": 3,
                                "praise_taps": 0,
                                "session_directory": "session-canary",
                            }
                        ),
                    ) as canary:
                        with patch(
                            "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse"
                        ) as supervised:
                            result = json.loads(pnsctl.nova_praise_pulse_live(args))
            canary.assert_called_once()
            supervised.assert_not_called()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["scenario_record"]["scenario_id"], "nova_navigation_round_trip_no_praise")
            self.assertEqual(result["scenario_record"]["input_class"], "navigation_only")

    def test_preflight_only_passes_without_runner_or_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            # Stale/missing delivery metadata must not block direct preflight.
            (root / "queue.json").write_text("{not-json", encoding="utf-8")
            args = pnsctl.parser().parse_args(
                self._identity_args(
                    evidence,
                    scenario="nova_praise_one_free_pulse",
                    extra=["--preflight-only"],
                )
            )
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                git = self._bind_supervised_args(args, root)
                guard_path = pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD
                with git:
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse"
                    ) as supervised:
                        result = json.loads(pnsctl.nova_praise_pulse_live(args))
                supervised.assert_not_called()
                self.assertEqual(result["status"], "preflight_passed")
                self.assertEqual(result["transport_calls"], 0)
                self.assertFalse(result["runtime_connected"])
                self.assertFalse(guard_path.exists())
                self.assertFalse((root / "lease.json").exists())

    def test_direct_live_ignores_stale_or_missing_delivery_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                head = "c" * 40
                result_payload = _valid_supervised_result(
                    action_database=str(pnsctl.NOVA_SUPERVISED_ACTION_DATABASE),
                    candidate_commit=None,
                    scenario_record=None,
                )
                result_payload.pop("candidate_commit", None)
                result_payload.pop("scenario_record", None)
                session = _write_realistic_session(root, result_payload)
                args = pnsctl.parser().parse_args(
                    self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
                )
                git = self._bind_supervised_args(args, root, head=head)
                runner_payload = {
                    "status": "completed",
                    "scenario_id": "nova_praise_one_free_pulse",
                    "navigation_input_count": 4,
                    "praise_transport_calls": 1,
                    "praise_taps": 1,
                    "session_directory": str(session),
                    "attempts_before": 6,
                    "attempts_after": 5,
                    "cooldown_seconds": 278,
                    "terminal_home_verified": True,
                    "journal_status": "confirmed",
                    "action_id": "nova-praise-action",
                    "action_key": "nova-praise:key",
                    "evidence_refs": result_payload["evidence_refs"],
                    "action_database": str(pnsctl.NOVA_SUPERVISED_ACTION_DATABASE),
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                }
                with git:
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                        return_value=json.dumps(runner_payload),
                    ):
                        result = json.loads(pnsctl.nova_praise_pulse_live(args))
                self.assertEqual(result["status"], "completed")
                # Queue/lease must remain unread/unrequired for direct execution.
                self.assertFalse((root / "queue.json").exists())
                self.assertFalse((root / "lease.json").exists())

    def test_execution_rejects_wrong_reset_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root, reset_id="game-day-other")
            args = pnsctl.parser().parse_args(
                self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
            )
            args.reset_id = "game-day-other"
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                git = self._bind_supervised_args(args, root)
                with git:
                    with self.assertRaisesRegex(pnsctl.OperatorError, "reset_id"):
                        pnsctl.nova_praise_pulse_live(args)

            evidence_ok = self._write_identity(root)
            args = pnsctl.parser().parse_args(
                self._identity_args(
                    evidence_ok,
                    scenario="nova_praise_one_free_pulse",
                    extra=["--action-database", str(root / "other.sqlite3")],
                )
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                args.output_directory = pnsctl.NOVA_NAVIGATION_CANARY_OUTPUT_DEFAULT
                git = self._bind_supervised_args(args, root)
                # Keep the alternate action-database after bind.
                args.action_database = root / "other.sqlite3"
                with git:
                    with self.assertRaisesRegex(pnsctl.OperatorError, "action database"):
                        pnsctl.nova_praise_pulse_live(args)

            args = pnsctl.parser().parse_args(
                self._identity_args(
                    evidence_ok,
                    scenario="nova_praise_one_free_pulse",
                    extra=["--output-directory", str(root / "other-out")],
                )
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                args.action_database = pnsctl.NOVA_SUPERVISED_ACTION_DATABASE
                git = patch(
                    "subprocess.run",
                    return_value=type("Proc", (), {"stdout": "a" * 40 + "\n", "returncode": 0})(),
                )
                with git:
                    with self.assertRaisesRegex(pnsctl.OperatorError, "output directory"):
                        pnsctl.nova_praise_pulse_live(args)

    def test_one_free_pulse_selects_supervised_runner_and_persists_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                head = "c" * 40
                result_payload = _valid_supervised_result(
                    action_database=str(pnsctl.NOVA_SUPERVISED_ACTION_DATABASE),
                    candidate_commit=None,
                    scenario_record=None,
                )
                result_payload.pop("candidate_commit", None)
                result_payload.pop("scenario_record", None)
                session = _write_realistic_session(root, result_payload)
                args = pnsctl.parser().parse_args(
                    self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
                )
                git = self._bind_supervised_args(args, root, head=head)
                runner_payload = {
                    "status": "completed",
                    "scenario_id": "nova_praise_one_free_pulse",
                    "navigation_input_count": 4,
                    "praise_transport_calls": 1,
                    "praise_taps": 1,
                    "session_directory": str(session),
                    "attempts_before": 6,
                    "attempts_after": 5,
                    "cooldown_seconds": 278,
                    "terminal_home_verified": True,
                    "journal_status": "confirmed",
                    "action_id": "nova-praise-action",
                    "action_key": "nova-praise:key",
                    "evidence_refs": result_payload["evidence_refs"],
                    "action_database": str(pnsctl.NOVA_SUPERVISED_ACTION_DATABASE),
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                }
                with git:
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                        return_value=json.dumps(runner_payload),
                    ) as supervised:
                        with patch(
                            "scripts.nova_praise_bluestacks.run_nova_navigation_canary"
                        ) as canary:
                            result = json.loads(pnsctl.nova_praise_pulse_live(args))
                supervised.assert_called_once()
                canary.assert_not_called()
                self.assertEqual(args.output_directory, pnsctl.NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(
                    result["scenario_record"]["input_class"],
                    "mixed_navigation_and_one_consequential",
                )
                persisted = json.loads((session / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(persisted["candidate_commit"], head)
                self.assertEqual(persisted["scenario_record"], result["scenario_record"])
                guard = json.loads(
                    pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD.read_text(encoding="utf-8")
                )
                self.assertEqual(guard["terminal_status"], "completed")
                self.assertEqual(guard["status"], "completed")

    def test_persist_failure_after_completed_runner_finalizes_non_completed_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                head = "f" * 40
                result_payload = _valid_supervised_result(
                    action_database=str(pnsctl.NOVA_SUPERVISED_ACTION_DATABASE),
                    candidate_commit=None,
                    scenario_record=None,
                )
                result_payload.pop("candidate_commit", None)
                result_payload.pop("scenario_record", None)
                session = _write_realistic_session(root, result_payload)
                args = pnsctl.parser().parse_args(
                    self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
                )
                git = self._bind_supervised_args(args, root, head=head)
                runner_payload = {
                    "status": "completed",
                    "scenario_id": "nova_praise_one_free_pulse",
                    "navigation_input_count": 4,
                    "praise_transport_calls": 1,
                    "praise_taps": 1,
                    "session_directory": str(session),
                    "attempts_before": 6,
                    "attempts_after": 5,
                    "cooldown_seconds": 278,
                    "terminal_home_verified": True,
                    "journal_status": "confirmed",
                    "action_id": "nova-praise-action",
                    "action_key": "nova-praise:key",
                    "evidence_refs": result_payload["evidence_refs"],
                    "action_database": str(pnsctl.NOVA_SUPERVISED_ACTION_DATABASE),
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                }
                finalized: list[dict] = []
                real_finalize = pnsctl._finalize_nova_supervised_invocation_guard

                def _capture_finalize(**kwargs):
                    finalized.append(dict(kwargs))
                    return real_finalize(**kwargs)

                with git:
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                        return_value=json.dumps(runner_payload),
                    ):
                        with patch.object(
                            pnsctl,
                            "_persist_nova_session_result",
                            side_effect=pnsctl.OperatorError("persist boom"),
                        ):
                            with patch.object(
                                pnsctl,
                                "_finalize_nova_supervised_invocation_guard",
                                side_effect=_capture_finalize,
                            ):
                                with self.assertRaisesRegex(pnsctl.OperatorError, "persist boom"):
                                    pnsctl.nova_praise_pulse_live(args)
                self.assertEqual(len(finalized), 1)
                self.assertNotEqual(finalized[0]["terminal_status"], "completed")
                self.assertEqual(finalized[0]["terminal_status"], "unresolved")
                self.assertEqual(finalized[0]["result_status"], "completed")
                self.assertEqual(finalized[0]["session_directory"], str(session))
                guard = json.loads(
                    pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD.read_text(encoding="utf-8")
                )
                self.assertEqual(guard["terminal_status"], "unresolved")
                self.assertEqual(guard["result_status"], "completed")
                self.assertTrue(pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD.is_file())

    def test_successful_completed_path_finalizes_completed_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                head = "g" * 40
                result_payload = _valid_supervised_result(
                    action_database=str(pnsctl.NOVA_SUPERVISED_ACTION_DATABASE),
                    candidate_commit=None,
                    scenario_record=None,
                )
                result_payload.pop("candidate_commit", None)
                result_payload.pop("scenario_record", None)
                session = _write_realistic_session(root, result_payload)
                args = pnsctl.parser().parse_args(
                    self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
                )
                git = self._bind_supervised_args(args, root, head=head)
                runner_payload = {
                    "status": "completed",
                    "scenario_id": "nova_praise_one_free_pulse",
                    "navigation_input_count": 4,
                    "praise_transport_calls": 1,
                    "praise_taps": 1,
                    "session_directory": str(session),
                    "attempts_before": 6,
                    "attempts_after": 5,
                    "cooldown_seconds": 278,
                    "terminal_home_verified": True,
                    "journal_status": "confirmed",
                    "action_id": "nova-praise-action",
                    "action_key": "nova-praise:key",
                    "evidence_refs": result_payload["evidence_refs"],
                    "action_database": str(pnsctl.NOVA_SUPERVISED_ACTION_DATABASE),
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                }
                finalized: list[dict] = []
                real_finalize = pnsctl._finalize_nova_supervised_invocation_guard

                def _capture_finalize(**kwargs):
                    finalized.append(dict(kwargs))
                    return real_finalize(**kwargs)

                with git:
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                        return_value=json.dumps(runner_payload),
                    ):
                        with patch.object(
                            pnsctl,
                            "_finalize_nova_supervised_invocation_guard",
                            side_effect=_capture_finalize,
                        ):
                            result = json.loads(pnsctl.nova_praise_pulse_live(args))
                self.assertEqual(result["status"], "completed")
                self.assertEqual(len(finalized), 1)
                self.assertEqual(finalized[0]["terminal_status"], "completed")
                self.assertEqual(finalized[0]["result_status"], "completed")

    def test_invocation_guard_blocks_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                head = "d" * 40
                pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD.parent.mkdir(parents=True, exist_ok=True)
                pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD.write_text(
                    json.dumps({"status": "started"}),
                    encoding="utf-8",
                )
                args = pnsctl.parser().parse_args(
                    self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
                )
                git = self._bind_supervised_args(args, root, head=head)
                with git:
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse"
                    ) as supervised:
                        with self.assertRaisesRegex(pnsctl.OperatorError, "invocation guard"):
                            pnsctl.nova_praise_pulse_live(args)
                supervised.assert_not_called()

    def test_unresolved_runner_marks_scenario_and_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                head = "e" * 40
                session = (
                    root
                    / ".local-captures"
                    / "flow-delivery"
                    / pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID
                    / "session-u"
                )
                session.mkdir(parents=True)
                (session / "result.json").write_text("{}\n", encoding="utf-8")
                args = pnsctl.parser().parse_args(
                    self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
                )
                git = self._bind_supervised_args(args, root, head=head)
                runner_payload = {
                    "status": "unresolved",
                    "reason": "praise_unresolved",
                    "navigation_input_count": 2,
                    "praise_transport_calls": 1,
                    "session_directory": str(session),
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                }
                with git:
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                        return_value=json.dumps(runner_payload),
                    ):
                        result = json.loads(pnsctl.nova_praise_pulse_live(args))
                self.assertEqual(result["scenario_record"]["outcome"], "unresolved")
                self.assertTrue(result["scenario_record"]["unresolved_action"])
                guard = json.loads(
                    pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD.read_text(encoding="utf-8")
                )
                self.assertEqual(guard["terminal_status"], "unresolved")

    def test_praise_then_home_return_failure_is_unresolved_no_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                head = "h" * 40
                session = (
                    root
                    / ".local-captures"
                    / "flow-delivery"
                    / pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID
                    / "session-home-fail"
                )
                session.mkdir(parents=True)
                (session / "result.json").write_text("{}\n", encoding="utf-8")
                args = pnsctl.parser().parse_args(
                    self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
                )
                git = self._bind_supervised_args(args, root, head=head)
                runner_payload = {
                    "status": "blocked",
                    "reason": "maximum_safe_return_inputs",
                    "navigation_input_count": 4,
                    "praise_transport_calls": 1,
                    "session_directory": str(session),
                    "terminal_home_verified": False,
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                }
                with git:
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                        return_value=json.dumps(runner_payload),
                    ):
                        result = json.loads(pnsctl.nova_praise_pulse_live(args))
                self.assertEqual(result["status"], "unresolved")
                self.assertEqual(result["reason"], "maximum_safe_return_inputs")
                self.assertEqual(result["scenario_record"]["outcome"], "unresolved")
                self.assertTrue(result["scenario_record"]["unresolved_action"])
                self.assertEqual(
                    result["scenario_record"]["input_class"],
                    "mixed_navigation_and_one_consequential",
                )
                persisted = json.loads((session / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(persisted["status"], "unresolved")
                self.assertEqual(persisted["scenario_record"]["outcome"], "unresolved")
                guard = json.loads(
                    pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD.read_text(encoding="utf-8")
                )
                self.assertEqual(guard["terminal_status"], "unresolved")
                self.assertEqual(guard["status"], "unresolved")
                self.assertTrue(pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD.is_file())

    def test_missing_session_directory_never_finalizes_completed_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                head = "i" * 40
                args = pnsctl.parser().parse_args(
                    self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
                )
                git = self._bind_supervised_args(args, root, head=head)
                runner_payload = {
                    "status": "completed",
                    "scenario_id": "nova_praise_one_free_pulse",
                    "navigation_input_count": 4,
                    "praise_transport_calls": 1,
                    "praise_taps": 1,
                    "session_directory": "",
                    "attempts_before": 6,
                    "attempts_after": 5,
                    "cooldown_seconds": 278,
                    "terminal_home_verified": True,
                    "journal_status": "confirmed",
                    "action_id": "nova-praise-action",
                    "action_key": "nova-praise:key",
                    "evidence_refs": ["before.png", "after.png"],
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                }
                finalized: list[dict] = []
                real_finalize = pnsctl._finalize_nova_supervised_invocation_guard

                def _capture_finalize(**kwargs):
                    finalized.append(dict(kwargs))
                    return real_finalize(**kwargs)

                with git:
                    with patch(
                        "scripts.nova_praise_bluestacks.run_nova_praise_one_free_pulse",
                        return_value=json.dumps(runner_payload),
                    ):
                        with patch.object(
                            pnsctl,
                            "_persist_nova_session_result",
                        ) as persist:
                            with patch.object(
                                pnsctl,
                                "_finalize_nova_supervised_invocation_guard",
                                side_effect=_capture_finalize,
                            ):
                                result = json.loads(pnsctl.nova_praise_pulse_live(args))
                persist.assert_not_called()
                self.assertEqual(result["status"], "unresolved")
                self.assertEqual(result["scenario_record"]["outcome"], "unresolved")
                self.assertTrue(result["scenario_record"]["unresolved_action"])
                self.assertEqual(len(finalized), 1)
                self.assertNotEqual(finalized[0]["terminal_status"], "completed")
                self.assertEqual(finalized[0]["terminal_status"], "unresolved")
                guard = json.loads(
                    pnsctl.NOVA_SUPERVISED_INVOCATION_GUARD.read_text(encoding="utf-8")
                )
                self.assertEqual(guard["terminal_status"], "unresolved")
                self.assertEqual(guard["status"], "unresolved")

    def test_action_database_cli_option_defaults_under_local_orchestrator(self) -> None:
        args = pnsctl.parser().parse_args(
            ["nova-praise-pulse", "--scenario", "nova_praise_one_free_pulse"]
        )
        self.assertEqual(args.action_database, pnsctl.NOVA_SUPERVISED_ACTION_DATABASE)
        self.assertEqual(args.scenario, "nova_praise_one_free_pulse")
        self.assertEqual(args.output_directory, pnsctl.NOVA_NAVIGATION_CANARY_OUTPUT_DEFAULT)
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            pnsctl.parser().parse_args(
                ["nova-praise-pulse", "--scenario", "unsupported_scenario"]
            )

    def test_direct_path_does_not_expose_queue_lease_admission_helpers(self) -> None:
        self.assertFalse(hasattr(pnsctl, "_require_nova_supervised_pulse_admission"))
        self.assertFalse(hasattr(pnsctl, "_load_nova_supervised_queue_lease"))

    def test_shared_lock_and_canonical_gate_required_for_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = self._write_identity(root)
            patches = self._patch_repo_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
                args = pnsctl.parser().parse_args(
                    self._identity_args(evidence, scenario="nova_praise_one_free_pulse")
                )
                git = self._bind_supervised_args(args, root, head="d" * 40)
                with git:
                    with patch.object(
                        nav_boundary.NavigationDevelopmentSession,
                        "__enter__",
                        side_effect=nav_boundary.NavigationBoundaryError(
                            "runtime input lock is held by another owner"
                        ),
                    ):
                        with self.assertRaisesRegex(
                            nav_boundary.NavigationBoundaryError,
                            "held by another owner",
                        ):
                            pnsctl.nova_praise_pulse_live(args)



class NovaSupervisedVerifyFlowTests(unittest.TestCase):
    def _patch_roots(self, root: Path):
        action_db = root / ".local-orchestrator" / "bluestacks-actions.sqlite3"
        return (
            patch.object(pnsctl, "REPO_ROOT", root),
            patch.object(pnsctl, "NOVA_SUPERVISED_ACTION_DATABASE", action_db),
        )

    def test_verifier_accepts_completed_supervised_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = _valid_supervised_result(
                action_database=str(root / ".local-orchestrator" / "bluestacks-actions.sqlite3")
            )
            session = _write_realistic_session(root, result)
            with self._patch_roots(root)[0], self._patch_roots(root)[1]:
                structure = pnsctl._verify_nova_supervised_one_free_pulse_session(session)
            self.assertEqual(structure["praise_transport_calls"], 1)
            self.assertEqual(structure["attempts_after"], 5)
            self.assertEqual(structure["cooldown_seconds"], 278)

    def test_verifier_rejects_missing_accounting_and_invalid_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = str(root / ".local-orchestrator" / "bluestacks-actions.sqlite3")
            missing = _write_realistic_session(
                root,
                _valid_supervised_result(action_database=db, candidate_commit=None, scenario_record=None),
            )
            payload = json.loads((missing / "result.json").read_text(encoding="utf-8"))
            payload.pop("candidate_commit", None)
            payload.pop("scenario_record", None)
            (missing / "result.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self._patch_roots(root)[0], self._patch_roots(root)[1]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "candidate_commit"):
                    pnsctl._verify_nova_supervised_one_free_pulse_session(missing)

            bad_root = root / "bad"
            bad = _write_realistic_session(
                bad_root,
                _valid_supervised_result(
                    action_database=str(bad_root / ".local-orchestrator" / "bluestacks-actions.sqlite3"),
                    cooldown_seconds=269,
                ),
            )
            with self._patch_roots(bad_root)[0], self._patch_roots(bad_root)[1]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "cooldown"):
                    pnsctl._verify_nova_supervised_one_free_pulse_session(bad)

    def test_verifier_rejects_sqlite_and_event_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / ".local-orchestrator" / "bluestacks-actions.sqlite3"
            session = _write_realistic_session(
                root,
                _valid_supervised_result(action_database=str(db)),
            )
            # Wrong final_status
            connection = sqlite3.connect(str(db))
            connection.execute(
                "UPDATE actions SET final_status='unresolved' WHERE action_id=?",
                ("nova-praise-action",),
            )
            connection.commit()
            connection.close()
            with self._patch_roots(root)[0], self._patch_roots(root)[1]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "final_status"):
                    pnsctl._verify_nova_supervised_one_free_pulse_session(session)

            connection = sqlite3.connect(str(db))
            connection.execute(
                "UPDATE actions SET final_status='confirmed', input_attempt_at=NULL WHERE action_id=?",
                ("nova-praise-action",),
            )
            connection.commit()
            connection.close()
            with self._patch_roots(root)[0], self._patch_roots(root)[1]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "input_attempt_at"):
                    pnsctl._verify_nova_supervised_one_free_pulse_session(session)

            connection = sqlite3.connect(str(db))
            connection.execute(
                "UPDATE actions SET input_attempt_at=2.0 WHERE action_id=?",
                ("nova-praise-action",),
            )
            connection.commit()
            connection.close()
            _write_jsonl(
                session / "events.jsonl",
                [{"type": "dispatch", "consequential": True, "action_key": "other"}],
            )
            with self._patch_roots(root)[0], self._patch_roots(root)[1]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "action_key"):
                    pnsctl._verify_nova_supervised_one_free_pulse_session(session)

            _write_jsonl(session / "events.jsonl", [])
            with self._patch_roots(root)[0], self._patch_roots(root)[1]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "nonempty"):
                    pnsctl._verify_nova_supervised_one_free_pulse_session(session)

    def test_bluestacks_verify_flow_uses_narrow_supervised_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / ".local-orchestrator" / "bluestacks-actions.sqlite3"
            session = _write_realistic_session(
                root,
                _valid_supervised_result(action_database=str(db)),
            )
            with self._patch_roots(root)[0], self._patch_roots(root)[1]:
                with patch.object(
                    pnsctl,
                    "_load_flow_delivery_state",
                    return_value=(
                        {"active_flow_id": pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID},
                        {"active_stage": "evidence_review", "workflow": "pns-flow-delivery"},
                    ),
                ):
                    with patch.object(pnsctl, "_verify_flow_structure") as generic:
                        verdict = json.loads(pnsctl.bluestacks_verify_flow(session))
            generic.assert_not_called()
            self.assertEqual(verdict["status"], "verified")
            self.assertEqual(verdict["flow_id"], pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID)
            self.assertEqual(verdict["praise_transport_calls"], 1)


if __name__ == "__main__":
    unittest.main()
