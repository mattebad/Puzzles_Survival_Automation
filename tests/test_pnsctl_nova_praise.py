"""Focused pnsctl tests for the retained Nova supervised-session verifier and guard reconciliation."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.pnsctl as pnsctl
from tasks.nova_praise_pulse import NOVA_TASK_ID


HISTORICAL_RESET_ID = "game-day-2026-07-22"


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
                ?, 'decrement', 'praise', 'none', 0, 1, 1, '{}',
                'allow', 'ok', 1.0, 2.0, '{}', '{}', '[]', 'confirmed', 'ok', 3.0
            )
            """,
            (action_id, action_key, NOVA_TASK_ID, HISTORICAL_RESET_ID),
        )
        store.connection.commit()
    finally:
        store.close()


def _seed_cancelled_praise_action(
    path: Path,
    *,
    action_id: str,
    action_key: str,
    reason: str = "CAPABILITY_CAPTURE_MISMATCH",
    final_status: str = "cancelled",
    input_attempt_at: float | None = None,
    transport_result_json: str | None = None,
    audit_transport_calls: int = 0,
    include_cancel_audit: bool = True,
) -> None:
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
                ?, ?, ?, 'PRAISE_NOVA', 'NOVA_PRAISE_ATTEMPTS_7', 'nova-praise', '[]',
                'abc', 1.0, 'profile', ?, 'decrement',
                'praise_zero_cost', 'none', 0, 1, 1, '{}', 'authorize', 'ok', 1.0,
                ?, ?, NULL, '[]', ?, ?, 3.0
            )
            """,
            (
                action_id,
                action_key,
                NOVA_TASK_ID,
                HISTORICAL_RESET_ID,
                input_attempt_at,
                transport_result_json,
                final_status,
                f"capability:{reason}" if final_status == "cancelled" else reason,
            ),
        )
        store.connection.execute(
            """
            INSERT INTO audit_events(
                action_id, task_id, event_type, lifecycle_from, lifecycle_to,
                recorded_at, payload_json
            ) VALUES (?, ?, 'action_transition', NULL, 'prepared', 1.0, ?)
            """,
            (action_id, NOVA_TASK_ID, json.dumps({"transport_calls": 0})),
        )
        store.connection.execute(
            """
            INSERT INTO audit_events(
                action_id, task_id, event_type, lifecycle_from, lifecycle_to,
                recorded_at, payload_json
            ) VALUES (?, ?, 'capability_consume', NULL, NULL, 2.0, ?)
            """,
            (
                action_id,
                NOVA_TASK_ID,
                json.dumps(
                    {
                        "reason_code": reason,
                        "transport_calls": audit_transport_calls,
                        "transport_occurred": None,
                    }
                ),
            ),
        )
        if include_cancel_audit:
            store.connection.execute(
                """
                INSERT INTO audit_events(
                    action_id, task_id, event_type, lifecycle_from, lifecycle_to,
                    recorded_at, payload_json
                ) VALUES (?, ?, 'action_transition', 'prepared', 'cancelled', 3.0, ?)
                """,
                (
                    action_id,
                    NOVA_TASK_ID,
                    json.dumps({"reason": f"capability:{reason}"}),
                ),
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
                    side_effect=pnsctl.OperatorError("no active delivery"),
                ):
                    with patch.object(pnsctl, "_verify_flow_structure") as generic:
                        verdict = json.loads(pnsctl.bluestacks_verify_flow(session))
            generic.assert_not_called()
            self.assertEqual(verdict["status"], "verified")
            self.assertEqual(verdict["flow_id"], pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID)
            self.assertEqual(verdict["praise_transport_calls"], 1)

    def _write_proven_no_effect_session(self, root: Path, **result_overrides) -> Path:
        output = root / ".local-captures" / "flow-delivery" / pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID
        session = output / "nova-praise-one-free-pulse-20260722T165950000000Z"
        session.mkdir(parents=True)
        action_db = str(root / ".local-orchestrator" / "bluestacks-actions.sqlite3")
        result = {
            "schema_version": 1,
            "flow_id": pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID,
            "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
            "status": "failed",
            "reason": "exception:StoreError",
            "navigation_input_count": 3,
            "session_directory": str(session),
            "action_database": action_db,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
        result.update(result_overrides)
        (session / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_jsonl(
            session / "events.jsonl",
            [
                {
                    "type": "capture",
                    "label": "canary-source",
                    "timestamp": "2026-07-22T16:59:44Z",
                },
                {
                    "type": "dispatch",
                    "consequential": False,
                    "action_key": "nova-canary:pan",
                    "timestamp": "2026-07-22T17:00:20Z",
                },
                {
                    "type": "capture",
                    "label": "praise-central-authorize",
                    "timestamp": "2026-07-22T17:01:17Z",
                },
                {
                    "type": "capture",
                    "label": "praise-central-pre-dispatch",
                    "timestamp": "2026-07-22T17:01:20Z",
                },
            ],
        )
        _write_jsonl(
            session / "capability-audit.jsonl",
            [
                {
                    "authority": "NavigationGuardedRuntime",
                    "authorized": True,
                    "consequential": False,
                    "transport_observed": True,
                },
                {
                    "authority": "NavigationGuardedRuntime",
                    "authorized": False,
                    "consequential": False,
                    "transport_observed": False,
                    "reason": "exception:StoreError",
                },
            ],
        )
        _write_jsonl(
            session / "journal.jsonl",
            [
                {
                    "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                    "status": "failed",
                    "reason": "exception:StoreError",
                    "navigation_input_count": 3,
                    "praise_transport_calls": 0,
                    "action_id": None,
                    "action_key": None,
                }
            ],
        )
        _write_jsonl(session / "ledger.jsonl", [{"action": "bounded_home_pan"}])
        return session

    def _unresolved_guard_payload(self, **overrides) -> dict:
        payload = {
            "schema_version": 1,
            "flow_id": pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID,
            "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
            "reset_id": HISTORICAL_RESET_ID,
            "candidate_commit": "a" * 40,
            "status": "unresolved",
            "terminal_status": "unresolved",
            "session_directory": None,
            "result_status": "unresolved",
            "started_at": "2026-07-22T16:59:42.000000Z",
            "finished_at": "2026-07-22T17:01:22.000000Z",
        }
        payload.update(overrides)
        return payload

    def _patch_guard_roots(self, root: Path):
        orchestrator = root / ".local-orchestrator"
        orchestrator.mkdir(parents=True, exist_ok=True)
        guard = orchestrator / f"nova-praise-one-free-pulse-{HISTORICAL_RESET_ID}.guard.json"
        action_db = orchestrator / "bluestacks-actions.sqlite3"
        output = root / ".local-captures" / "flow-delivery" / pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID
        return (
            patch.object(pnsctl, "REPO_ROOT", root),
            patch.object(pnsctl, "NOVA_SUPERVISED_ACTION_DATABASE", action_db),
            patch.object(
                pnsctl,
                "NOVA_SUPERVISED_GUARD_ARCHIVE_DIR",
                orchestrator / "nova-supervised-guard-archive",
            ),
            patch.object(
                pnsctl,
                "NOVA_SUPERVISED_GUARD_ARCHIVE_DIR",
                orchestrator / "nova-supervised-guard-archive",
            ),
            patch.object(
                pnsctl,
                "NOVA_SUPERVISED_GUARD_RECEIPT_DIR",
                orchestrator / "nova-supervised-guard-receipts",
            ),
            patch.object(pnsctl, "NOVA_SUPERVISED_PULSE_OUTPUT_DEFAULT", output),
            guard,
            action_db,
        )

    def test_reconcile_normal_missing_commit_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(root)
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(session_directory=str(session)),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "candidate_commit is required"):
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
            self.assertTrue(guard_path.exists())

    def test_reconcile_legacy_mode_required_for_null_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(root)
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            guard_path.write_text(
                json.dumps(self._unresolved_guard_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with self.assertRaisesRegex(
                    pnsctl.OperatorError, "legacy-null-session-recovery"
                ):
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
            self.assertTrue(guard_path.exists())

    def test_reconcile_legacy_wrong_head_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(root)
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            guard_path.write_text(
                json.dumps(self._unresolved_guard_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with patch("subprocess.run") as run:
                    run.return_value = type(
                        "Proc",
                        (),
                        {"stdout": "b" * 40 + "\n", "returncode": 0},
                    )()
                    with self.assertRaisesRegex(pnsctl.OperatorError, "git HEAD"):
                        pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(
                            session,
                            legacy_null_session_recovery=True,
                            expected_candidate_commit="a" * 40,
                        )
            self.assertTrue(guard_path.exists())

    def test_reconcile_legacy_sibling_in_window_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(root)
            sibling = (
                root
                / ".local-captures"
                / "flow-delivery"
                / pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID
                / "nova-praise-one-free-pulse-20260722T165955000000Z"
            )
            sibling.mkdir(parents=True)
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            guard_path.write_text(
                json.dumps(self._unresolved_guard_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with patch("subprocess.run") as run:
                    run.return_value = type(
                        "Proc",
                        (),
                        {"stdout": "a" * 40 + "\n", "returncode": 0},
                    )()
                    with self.assertRaisesRegex(pnsctl.OperatorError, "multiple supervised sessions"):
                        pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(
                            session,
                            legacy_null_session_recovery=True,
                            expected_candidate_commit="a" * 40,
                        )
            self.assertTrue(guard_path.exists())

    def test_reconcile_legacy_unique_session_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(root)
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            guard_path.write_text(
                json.dumps(self._unresolved_guard_payload(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with patch("subprocess.run") as run:
                    run.return_value = type(
                        "Proc",
                        (),
                        {"stdout": "a" * 40 + "\n", "returncode": 0},
                    )()
                    payload = json.loads(
                        pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(
                            session,
                            legacy_null_session_recovery=True,
                            expected_candidate_commit="a" * 40,
                        )
                    )
            self.assertEqual(payload["status"], "reconciled")
            self.assertTrue(payload["legacy_null_session_recovery"])
            self.assertFalse(guard_path.exists())
            receipt = json.loads(Path(payload["receipt_path"]).read_text(encoding="utf-8"))
            self.assertTrue(receipt["legacy_null_session_recovery"])
            self.assertEqual(receipt["proof"]["expected_candidate_commit"], "a" * 40)
            self.assertEqual(receipt["proof"]["current_head"], "a" * 40)
            self.assertIn("result.json", receipt["proof"]["evidence_hashes"])

    def test_reconcile_normal_bound_session_with_commit_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(
                root,
                candidate_commit="a" * 40,
            )
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(session_directory=str(session)),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                payload = json.loads(
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
                )
            self.assertEqual(payload["status"], "reconciled")
            self.assertFalse(payload["legacy_null_session_recovery"])
            self.assertFalse(guard_path.exists())

    def test_bind_guard_session_and_persist_candidate_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            session = self._write_proven_no_effect_session(root)
            guard_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "flow_id": pnsctl.NOVA_SUPERVISED_PULSE_FLOW_ID,
                        "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                        "reset_id": HISTORICAL_RESET_ID,
                        "candidate_commit": "a" * 40,
                        "status": "started",
                        "terminal_status": None,
                        "session_directory": None,
                        "started_at": "2026-07-22T16:59:42.000000Z",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                pnsctl._bind_nova_supervised_invocation_guard_session(str(session))
                persisted = pnsctl._persist_nova_session_result(
                    session,
                    {"status": "failed", "reason": "unit"},
                    candidate_commit="a" * 40,
                )
            guard = json.loads(guard_path.read_text(encoding="utf-8"))
            self.assertEqual(Path(guard["session_directory"]), session.resolve())
            self.assertEqual(guard["status"], "started")
            self.assertEqual(persisted["candidate_commit"], "a" * 40)
            self.assertEqual(Path(persisted["session_directory"]), session.resolve())

    def test_reconcile_proven_no_effect_fails_closed_on_consequential_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(
                root,
                candidate_commit="a" * 40,
            )
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            _write_jsonl(
                session / "events.jsonl",
                [
                    {
                        "type": "capture",
                        "label": "praise-central-authorize",
                        "timestamp": "2026-07-22T17:01:17Z",
                    },
                    {
                        "type": "dispatch",
                        "consequential": True,
                        "action_key": "nova-praise:key",
                        "timestamp": "2026-07-22T17:01:21Z",
                    },
                ],
            )
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(session_directory=str(session)),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "consequential transport"):
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
            self.assertTrue(guard_path.exists())

    def test_reconcile_proven_no_effect_fails_closed_on_store_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(
                root,
                candidate_commit="a" * 40,
            )
            _seed_action_database(action_db, action_id="nova-praise-action", action_key="nova-praise:key")
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(session_directory=str(session)),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "action rows"):
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
            self.assertTrue(guard_path.exists())

    def test_reconcile_proven_no_effect_ignores_only_no_effect_cancelled_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(
                root,
                candidate_commit="a" * 40,
            )
            _seed_cancelled_praise_action(
                action_db,
                action_id="cancelled-nova-praise",
                action_key="nova-praise:cancelled",
            )
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(session_directory=str(session)),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                payload = json.loads(
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
                )

            self.assertEqual(payload["status"], "reconciled")
            receipt = json.loads(Path(payload["receipt_path"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["proof"]["action_rows"], 0)
            self.assertFalse(guard_path.exists())

    def test_reconcile_proven_no_effect_rejects_transported_or_unresolved_rows(self) -> None:
        cases = (
            ("input_sent", 2.0, "{}"),
            ("unresolved", None, None),
            ("confirmed", 2.0, "{}"),
        )
        for final_status, input_attempt_at, transport_result_json in cases:
            with self.subTest(final_status=final_status):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    patches = self._patch_guard_roots(root)
                    guard_path = patches[6]
                    action_db = patches[7]
                    session = self._write_proven_no_effect_session(
                        root,
                        candidate_commit="a" * 40,
                    )
                    _seed_cancelled_praise_action(
                        action_db,
                        action_id=f"{final_status}-nova-praise",
                        action_key=f"nova-praise:{final_status}",
                        final_status=final_status,
                        input_attempt_at=input_attempt_at,
                        transport_result_json=transport_result_json,
                    )
                    guard_path.write_text(
                        json.dumps(
                            self._unresolved_guard_payload(session_directory=str(session)),
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )

                    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                        with self.assertRaisesRegex(
                            pnsctl.OperatorError,
                            "action rows",
                        ):
                            pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(
                                session
                            )
                    self.assertTrue(guard_path.exists())

    def test_reconcile_blocked_guard_zero_transport_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            reason = "fresh_nova_target_not_bound"
            session = self._write_proven_no_effect_session(
                root,
                candidate_commit="a" * 40,
                status="blocked",
                reason=reason,
                praise_transport_calls=0,
                navigation_input_count=2,
                scenario_record={
                    "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                    "outcome": "blocked",
                    "reason": reason,
                    "unresolved_action": False,
                    "praise_transport_calls": 0,
                    "navigation_input_count": 2,
                    "input_class": "navigation_only",
                },
            )
            # Pre-Praise blocked: no praise-central captures (never entered Praise).
            _write_jsonl(
                session / "events.jsonl",
                [
                    {
                        "type": "capture",
                        "label": "canary-source",
                        "timestamp": "2026-07-22T17:52:39Z",
                    },
                    {
                        "type": "dispatch",
                        "consequential": False,
                        "action_key": "nova-canary:pan",
                        "timestamp": "2026-07-22T17:53:22Z",
                    },
                    {
                        "type": "capture",
                        "label": "canary-open-nova-immediate-before",
                        "timestamp": "2026-07-22T17:54:05Z",
                    },
                ],
            )
            _write_jsonl(
                session / "capability-audit.jsonl",
                [
                    {
                        "authority": "NavigationGuardedRuntime",
                        "authorized": True,
                        "consequential": False,
                        "transport_observed": True,
                        "target_identity": "home-camera-click-drag",
                    },
                    {
                        "authority": "NavigationGuardedRuntime",
                        "authorized": True,
                        "consequential": False,
                        "transport_observed": True,
                        "target_identity": "home.building.research_lab",
                    },
                ],
            )
            _write_jsonl(
                session / "journal.jsonl",
                [
                    {
                        "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                        "status": "blocked",
                        "reason": reason,
                        "navigation_input_count": 2,
                        "praise_transport_calls": 0,
                        "action_id": None,
                        "action_key": None,
                    }
                ],
            )
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(
                        status="blocked",
                        terminal_status="blocked",
                        result_status="blocked",
                        session_directory=str(session),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                payload = json.loads(
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
                )
            self.assertEqual(payload["status"], "reconciled")
            self.assertFalse(guard_path.exists())
            journal = json.loads(
                (session / "journal.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
            )
            self.assertNotIn("flow_id", journal)
            events = [
                json.loads(line)
                for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertFalse(
                any(
                    str(event.get("label") or "").startswith("praise-central-")
                    for event in events
                )
            )
            receipt = json.loads(Path(payload["receipt_path"]).read_text(encoding="utf-8"))
            self.assertTrue(receipt["blocked_guard_reconcile"])
            self.assertEqual(receipt["proof"]["result_status"], "blocked")
            self.assertEqual(receipt["proof"]["result_reason"], reason)

    def test_reconcile_zero_input_block_allows_empty_capability_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            current_reset = "game-day-2026-08-18"
            guard_path = patches[6].with_name(
                f"nova-praise-one-free-pulse-{current_reset}.guard.json"
            )
            action_db = patches[7]
            reason = "initial_surface_not_home_or_known_nova_context"
            session = self._write_proven_no_effect_session(
                root,
                candidate_commit="a" * 40,
                status="blocked",
                reason=reason,
                praise_transport_calls=0,
                navigation_input_count=0,
                scenario_record={
                    "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                    "outcome": "blocked",
                    "reason": reason,
                    "unresolved_action": False,
                    "praise_transport_calls": 0,
                    "navigation_input_count": 0,
                    "input_class": "none",
                },
            )
            _write_jsonl(
                session / "events.jsonl",
                [{"type": "capture", "label": "canary-source"}],
            )
            (session / "capability-audit.jsonl").write_text("", encoding="utf-8")
            _write_jsonl(
                session / "journal.jsonl",
                [
                    {
                        "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                        "status": "blocked",
                        "reason": reason,
                        "navigation_input_count": 0,
                        "praise_transport_calls": 0,
                        "action_id": None,
                        "action_key": None,
                    }
                ],
            )
            _seed_action_database(
                action_db,
                action_id="historical-confirmed-praise",
                action_key="nova-praise:historical-confirmed",
            )
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(
                        status="blocked",
                        terminal_status="blocked",
                        result_status="blocked",
                        reset_id=current_reset,
                        session_directory=str(session),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                payload = json.loads(
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(
                        session,
                        reset_id=current_reset,
                    )
                )
            self.assertEqual(payload["status"], "reconciled")
            receipt = json.loads(
                Path(payload["receipt_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["proof"]["capability_audit_count"], 0)
            self.assertFalse(guard_path.exists())

    def test_reconcile_blocked_guard_status_mismatch_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_proven_no_effect_session(
                root,
                candidate_commit="a" * 40,
                status="failed",
                reason="exception:StoreError",
                praise_transport_calls=0,
            )
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(
                        status="blocked",
                        terminal_status="blocked",
                        result_status="blocked",
                        session_directory=str(session),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "result.status == blocked"):
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
            self.assertTrue(guard_path.exists())

    def test_reconcile_blocked_guard_transport_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            reason = "fresh_nova_target_not_bound"
            session = self._write_proven_no_effect_session(
                root,
                candidate_commit="a" * 40,
                status="blocked",
                reason=reason,
                praise_transport_calls=1,
                scenario_record={
                    "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                    "outcome": "blocked",
                    "reason": reason,
                    "unresolved_action": False,
                    "praise_transport_calls": 1,
                    "navigation_input_count": 3,
                },
            )
            _write_jsonl(
                session / "journal.jsonl",
                [
                    {
                        "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                        "status": "blocked",
                        "reason": reason,
                        "navigation_input_count": 3,
                        "praise_transport_calls": 1,
                        "action_id": None,
                        "action_key": None,
                    }
                ],
            )
            from safe_action_core import SafetyStore

            store = SafetyStore(action_db)
            store.close()
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(
                        status="blocked",
                        terminal_status="blocked",
                        result_status="blocked",
                        session_directory=str(session),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "praise_transport_calls == 0"):
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
            self.assertTrue(guard_path.exists())

    def _write_praise_cancelled_session(
        self,
        root: Path,
        action_db: Path,
        *,
        reason: str = "CAPABILITY_CAPTURE_MISMATCH",
        action_id: str = "nova-praise-cancelled-1",
        action_key: str = "nova-praise:cancelled-1",
        seed_kwargs: dict | None = None,
    ) -> Path:
        session = self._write_proven_no_effect_session(
            root,
            candidate_commit="a" * 40,
            status="blocked",
            reason=reason,
            praise_transport_calls=0,
            navigation_input_count=1,
            action_id=action_id,
            action_key=action_key,
            scenario_record={
                "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                "outcome": "blocked",
                "reason": reason,
                "unresolved_action": False,
                "praise_transport_calls": 0,
                "navigation_input_count": 1,
                "input_class": "navigation_only",
            },
        )
        _write_jsonl(
            session / "events.jsonl",
            [
                {
                    "type": "capture",
                    "label": "canary-source",
                    "timestamp": "2026-07-22T18:17:50Z",
                },
                {
                    "type": "dispatch",
                    "consequential": False,
                    "action_key": "nova-canary:open-nova",
                    "timestamp": "2026-07-22T18:18:10Z",
                },
                {
                    "type": "capture",
                    "label": "praise-central-authorize",
                    "timestamp": "2026-07-22T18:18:40Z",
                },
                {
                    "type": "capture",
                    "label": "praise-central-pre-dispatch",
                    "timestamp": "2026-07-22T18:18:42Z",
                },
            ],
        )
        _write_jsonl(
            session / "capability-audit.jsonl",
            [
                {
                    "authority": "NavigationGuardedRuntime",
                    "authorized": True,
                    "consequential": False,
                    "transport_observed": True,
                    "target_identity": "research-lab-nova",
                }
            ],
        )
        _write_jsonl(
            session / "journal.jsonl",
            [
                {
                    "scenario_id": pnsctl.NOVA_SUPERVISED_PULSE_SCENARIO_ID,
                    "status": "blocked",
                    "navigation_input_count": 1,
                    "praise_transport_calls": 0,
                    "action_id": action_id,
                    "action_key": action_key,
                }
            ],
        )
        _seed_cancelled_praise_action(
            action_db,
            action_id=action_id,
            action_key=action_key,
            reason=reason,
            **(seed_kwargs or {}),
        )
        return session

    def test_reconcile_praise_cancelled_zero_transport_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_praise_cancelled_session(root, action_db)
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(
                        status="blocked",
                        terminal_status="blocked",
                        result_status="blocked",
                        session_directory=str(session),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                payload = json.loads(
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
                )
            self.assertEqual(payload["status"], "reconciled")
            self.assertFalse(guard_path.exists())
            receipt = json.loads(Path(payload["receipt_path"]).read_text(encoding="utf-8"))
            self.assertTrue(receipt["proof"]["praise_cancelled_before_transport"])
            self.assertEqual(receipt["proof"]["bound_action_final_status"], "cancelled")
            self.assertGreaterEqual(receipt["proof"]["action_rows"], 1)

    def test_reconcile_praise_cancelled_transport_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_praise_cancelled_session(
                root,
                action_db,
                seed_kwargs={"audit_transport_calls": 1},
            )
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(
                        status="blocked",
                        terminal_status="blocked",
                        result_status="blocked",
                        session_directory=str(session),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "transport_calls must be zero"):
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
            self.assertTrue(guard_path.exists())

    def test_reconcile_praise_cancelled_unresolved_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_praise_cancelled_session(
                root,
                action_db,
                seed_kwargs={
                    "final_status": "unresolved",
                    "include_cancel_audit": False,
                },
            )
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(
                        status="blocked",
                        terminal_status="blocked",
                        result_status="blocked",
                        session_directory=str(session),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "final_status=unresolved"):
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
            self.assertTrue(guard_path.exists())

    def test_reconcile_praise_cancelled_id_mismatch_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patches = self._patch_guard_roots(root)
            guard_path = patches[6]
            action_db = patches[7]
            session = self._write_praise_cancelled_session(root, action_db)
            result = json.loads((session / "result.json").read_text(encoding="utf-8"))
            result["action_id"] = "nova-praise-other"
            (session / "result.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            guard_path.write_text(
                json.dumps(
                    self._unresolved_guard_payload(
                        status="blocked",
                        terminal_status="blocked",
                        result_status="blocked",
                        session_directory=str(session),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                with self.assertRaisesRegex(pnsctl.OperatorError, "missing from SafetyStore|action_id"):
                    pnsctl.reconcile_nova_supervised_invocation_guard_proven_no_effect(session)
            self.assertTrue(guard_path.exists())


if __name__ == "__main__":
    unittest.main()
