from __future__ import annotations

import contextlib
from io import StringIO
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from automation_service.registry import (
    CAMPAIGN_FLOW_ID,
    NOVA_FLOW_ID,
    RECRUITMENT_FLOW_ID,
    WORLD_FLOW_ID,
)
from automation_service.state import BotStateManager

from scripts.pnsctl import (
    OperatorError,
    _compact_development_action_results,
    _retained_semantic_completed_count,
    _retained_transport_count,
    _startup_recovery_action_rows,
    _unique_action_rows,
    main,
)





class PnsctlSchedulerPulseTests(unittest.TestCase):
    def test_retained_action_projection_deduplicates_transport_and_keeps_semantics(self):
        rows = [
            {
                "type": "dispatch",
                "action_key": "same-action",
                "target_identity": "target",
                "source_sha256": "before",
                "execute": True,
            },
            {
                "type": "capture",
                "label": "post",
                "path": r"historical:stream\post.png",
                "sha256": "after",
            },
            {
                "type": "dispatch",
                "action_key": "same-action",
                "target_identity": "target",
                "source_sha256": "before",
                "execute": True,
            },
            {
                "type": "capture",
                "label": "duplicate-post",
                "path": "duplicate-post.png",
                "sha256": "duplicate-after",
            },
            {
                "type": "reconcile",
                "action_key": "same-action",
                "status": "unresolved",
                "reason": "unknown successor",
            },
        ]
        actions = _compact_development_action_results(rows)
        self.assertEqual(_retained_transport_count(rows), 1)
        self.assertEqual(_retained_semantic_completed_count(actions), 0)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["semantic_status"], "unresolved")
        self.assertFalse(actions[0]["semantic_completed"])
        self.assertEqual(actions[0]["capture_status"], "post_captured")
        self.assertEqual(actions[0]["after_path"], r"historical:stream\post.png")

    def test_canonical_action_rows_count_failed_unknown_once_without_capture_success(self):
        rows = [
            {"label": "confirmed", "status": "completed"},
            {"label": "confirmed", "status": "unknown", "transport_attempted_count": 2},
            {"label": "positive", "status": "completed"},
            {"label": "failed", "status": "effect_reconciliation_required"},
            {"label": "unknown", "status": "unknown"},
        ]
        self.assertEqual(_retained_transport_count(rows), 5)
        self.assertEqual(_retained_semantic_completed_count(rows), 1)
    def test_startup_recovery_action_keeps_one_action_distinct_from_multiple_inputs(self):
        recovery = {
            "status": "recovered",
            "input_count": 2,
            "action_key": "startup-recovery:close",
            "popup_identity": "reset-popup",
            "before_sha256": "before",
            "after_sha256": "after",
            "reason": "successor recognized",
        }
        rows = _startup_recovery_action_rows(recovery)
        self.assertEqual(len(rows), 1)
        self.assertEqual(_retained_transport_count(rows), 2)
        self.assertEqual(_retained_semantic_completed_count(rows), 1)
        self.assertEqual(rows[0]["action_key"], recovery["action_key"])
        self.assertEqual(rows[0]["status"], "completed")
        combined = _unique_action_rows([*rows, *rows])
        self.assertEqual(_retained_transport_count(combined), 2)
        self.assertEqual(_retained_semantic_completed_count(combined), 1)

    def test_nonattempted_dispatch_is_excluded_without_losing_label_identity(self):
        events = [
            {"type": "dispatch", "execute": True, "transport_attempted": False},
            {"type": "dispatch", "execute": True, "label": "actual-label"},
        ]
        actions = _compact_development_action_results(events)
        self.assertEqual([row["action_key"] for row in actions], ["actual-label"])
        self.assertEqual(_retained_transport_count(events), 1)
        self.assertEqual(_retained_transport_count(actions), 1)
        self.assertEqual(_retained_semantic_completed_count(actions), 0)

    def test_malformed_executable_ledger_cannot_silently_undercount(self):
        for event in (
            {"type": "dispatch", "execute": True},
            {"type": "dispatch", "execute": True, "action_key": "action", "transport_attempted_count": -1},
        ):
            with self.subTest(event=event):
                with self.assertRaises(OperatorError):
                    _compact_development_action_results([event])
                with self.assertRaises(OperatorError):
                    _retained_transport_count([event])

    def test_semantic_count_rejects_identityless_actions_but_ignores_capture_events(self):
        for row in (
            {"status": "completed"},
            {"type": "reconcile", "semantic_status": "confirmed"},
            {"type": "dispatch", "execute": True},
        ):
            with self.subTest(row=row):
                with self.assertRaises(OperatorError):
                    _retained_semantic_completed_count([row])
        self.assertEqual(
            _retained_semantic_completed_count([
                {"type": "capture", "semantic_status": "confirmed"},
                {"action_key": "confirmed-action", "status": "completed"},
            ]),
            1,
        )

    def test_terminal_reconciliation_cannot_be_overwritten(self):
        dispatch = {"type": "dispatch", "action_key": "action", "execute": True}
        for first, later in (
            ("failed_confirmed", "confirmed"),
            ("confirmed", "failed_confirmed"),
            ("failed_confirmed", "unresolved"),
        ):
            with self.subTest(first=first, later=later):
                events = [dispatch, *(
                    {"type": "reconcile", "action_key": "action", "status": status}
                    for status in (first, later)
                )]
                with self.assertRaises(OperatorError):
                    _compact_development_action_results(events)

    def test_unresolved_action_can_reconcile_to_one_terminal_outcome(self):
        for terminal, completed in (("confirmed", 1), ("failed_confirmed", 0)):
            with self.subTest(terminal=terminal):
                events = [
                    {"type": "dispatch", "action_key": "action", "execute": True},
                    *(
                        {"type": "reconcile", "action_key": "action", "status": status}
                        for status in ("unresolved", terminal, terminal)
                    ),
                ]
                actions = _compact_development_action_results(events)
                self.assertEqual(_retained_transport_count(actions), 1)
                self.assertEqual(_retained_semantic_completed_count(actions), completed)
                self.assertEqual(actions[0]["semantic_status"], terminal)


    def test_pulse_contention_is_structured_and_never_selected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pulse-busy.sqlite3"
            seed = BotStateManager(path)
            seed.close()
            holder = sqlite3.connect(path, timeout=0.01, isolation_level=None)

            class ShortTimeoutManager(BotStateManager):
                def __init__(self, db_path=None, **kwargs):
                    kwargs["busy_timeout_ms"] = 25
                    super().__init__(db_path, **kwargs)

            try:
                holder.execute("BEGIN IMMEDIATE")
                error_output = StringIO()
                with patch(
                    "automation_service.state.BotStateManager",
                    ShortTimeoutManager,
                ), contextlib.redirect_stderr(error_output):
                    self.assertEqual(
                        main(
                            [
                                "automation-service",
                                "pulse",
                                "--state-path",
                                str(path),
                                "--health-ok",
                            ]
                        ),
                        2,
                    )
                self.assertEqual(
                    json.loads(error_output.getvalue()),
                    {"reason": "SQLITE_BUSY", "retryable": True, "status": "error"},
                )
            finally:
                holder.rollback()
                holder.close()

    def test_manual_run_accepts_operator_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manual.sqlite3"
            with contextlib.redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "service-enable",
                            "--state-path",
                            str(path),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "enable",
                            WORLD_FLOW_ID,
                            "--state-path",
                            str(path),
                        ]
                    ),
                    0,
                )
            output = StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "run",
                            WORLD_FLOW_ID,
                            "--mode",
                            "dry_run",
                            "--live",
                            "--state-path",
                            str(path),
                            "--operator-request-id",
                            "operator-pnsctl-test",
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["candidate"]["flow_id"], WORLD_FLOW_ID)
            self.assertTrue(
                payload["candidate"]["occurrence_key"].endswith(
                    ":manual:operator-pnsctl-test"
                )
            )
    def _enable_sqlite_gates(self, path: Path, flow_id: str) -> None:
        with contextlib.redirect_stdout(StringIO()):
            self.assertEqual(
                main(
                    [
                        "automation-service",
                        "service-enable",
                        "--state-path",
                        str(path),
                        "--now-utc-epoch",
                        "1",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "automation-service",
                        "enable",
                        flow_id,
                        "--state-path",
                        str(path),
                        "--now-utc-epoch",
                        "1",
                    ]
                ),
                0,
            )

    def test_pulse_without_state_path_is_disabled_and_zero_transport(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            default_path = Path(folder) / "default.sqlite3"
            output = StringIO()
            with (
                patch.object(BotStateManager, "DEFAULT_DB_PATH", str(default_path)),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(main(["automation-service", "pulse"]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "disabled")
        self.assertEqual(payload["reason"], "GLOBAL_HEALTH_BREAKER")
        self.assertEqual(payload["production_registration"], "REGISTERED")
        self.assertEqual(payload["accepted_product"], "world_map_navigation")
        self.assertEqual(payload["transport_count"], 0)
        self.assertFalse(payload["scheduler_eligible"])

    def test_pulse_with_state_path_persists_nothing_when_health_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            output = StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "pulse",
                            "--state-path",
                            str(path),
                            "--now-utc-epoch",
                            "100",
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "disabled")
            self.assertEqual(payload["transport_count"], 0)
            self.assertEqual(payload["reason"], "GLOBAL_HEALTH_BREAKER")
            self.assertFalse(payload["scheduler_eligible"])

    def test_healthy_pulse_requires_sqlite_service_and_flow_enablement(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            base = [
                "automation-service",
                "pulse",
                "--state-path",
                str(path),
                "--flow-id",
                NOVA_FLOW_ID,
                "--now-utc-epoch",
                "100",
                "--health-ok",
            ]

            disabled = StringIO()
            with contextlib.redirect_stdout(disabled):
                self.assertEqual(main(base), 0)
            disabled_payload = json.loads(disabled.getvalue())
            self.assertEqual(disabled_payload["reason"], "SERVICE_DISABLED")
            self.assertFalse(disabled_payload["scheduler_eligible"])

            with contextlib.redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "service-enable",
                            "--state-path",
                            str(path),
                            "--now-utc-epoch",
                            "101",
                        ]
                    ),
                    0,
                )

            flow_disabled = StringIO()
            with contextlib.redirect_stdout(flow_disabled):
                self.assertEqual(main(base), 0)
            flow_disabled_payload = json.loads(flow_disabled.getvalue())
            self.assertEqual(flow_disabled_payload["status"], "disabled")
            self.assertEqual(flow_disabled_payload["reason"], "NO_ELIGIBLE_TASK")
            self.assertFalse(flow_disabled_payload["scheduler_eligible"])
            self.assertEqual(flow_disabled_payload["transport_count"], 0)

            with contextlib.redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "automation-service",
                            "enable",
                            NOVA_FLOW_ID,
                            "--state-path",
                            str(path),
                            "--now-utc-epoch",
                            "102",
                        ]
                    ),
                    0,
                )

            selected = StringIO()
            with contextlib.redirect_stdout(selected):
                self.assertEqual(main(base), 0)
            payload = json.loads(selected.getvalue())
            self.assertEqual(payload["status"], "selected")
            self.assertEqual(payload["candidate"]["flow_id"], NOVA_FLOW_ID)
            self.assertEqual(
                payload["result"]["reason_code"],
                "NOVA_PRAISE_PARENT_CANARY_REQUIRED",
            )
            self.assertEqual(payload["transport_count"], 0)
            self.assertEqual(payload["accepted_product"], "nova_praise")
            self.assertTrue(payload["scheduler_eligible"])

    def test_recruitment_pulse_requires_fresh_due_projection_and_is_restart_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            self._enable_sqlite_gates(path, RECRUITMENT_FLOW_ID)
            base = [
                "automation-service",
                "pulse",
                "--state-path",
                str(path),
                "--flow-id",
                RECRUITMENT_FLOW_ID,
                "--now-utc-epoch",
                "100",
                "--health-ok",
            ]
            missing = StringIO()
            with contextlib.redirect_stdout(missing):
                self.assertEqual(main(base), 0)
            missing_payload = json.loads(missing.getvalue())
            self.assertEqual(missing_payload["status"], "disabled")
            self.assertEqual(missing_payload["reason"], "NO_ELIGIBLE_TASK")
            self.assertTrue(missing_payload["scheduler_eligible"])

            selected = StringIO()
            with contextlib.redirect_stdout(selected):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--projection-observed-at-utc",
                            "95",
                            "--projection-next-eligible-at",
                            "90",
                        ]
                    ),
                    0,
                )
            payload = json.loads(selected.getvalue())
            self.assertEqual(payload["status"], "selected")
            self.assertEqual(payload["candidate"]["flow_id"], RECRUITMENT_FLOW_ID)
            self.assertEqual(
                payload["result"]["reason_code"],
                "RECRUITMENT_MAINTENANCE_PARENT_CANARY_REQUIRED",
            )
            self.assertEqual(payload["transport_count"], 0)
            self.assertTrue(payload["scheduler_eligible"])
            accepted_occurrence_key = payload["candidate"]["occurrence_key"]
            self.assertEqual(
                accepted_occurrence_key,
                f"{RECRUITMENT_FLOW_ID}:cooldown:90.0",
            )

            duplicate = StringIO()
            with contextlib.redirect_stdout(duplicate):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--projection-observed-at-utc",
                            "95",
                            "--projection-next-eligible-at",
                            "90",
                        ]
                    ),
                    0,
                )
            duplicate_payload = json.loads(duplicate.getvalue())
            self.assertEqual(duplicate_payload["status"], "disabled")
            self.assertEqual(
                duplicate_payload["reason"],
                "NO_ELIGIBLE_TASK",
            )
            changed_observation = StringIO()
            with contextlib.redirect_stdout(changed_observation):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--projection-observed-at-utc",
                            "96",
                            "--projection-next-eligible-at",
                            "90",
                        ]
                    ),
                    0,
                )
            changed_observation_payload = json.loads(changed_observation.getvalue())
            self.assertEqual(changed_observation_payload["status"], "disabled")
            self.assertEqual(
                changed_observation_payload["reason"],
                "NO_ELIGIBLE_TASK",
            )
            new_slot = StringIO()
            with contextlib.redirect_stdout(new_slot):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--projection-observed-at-utc",
                            "96",
                            "--projection-next-eligible-at",
                            "91",
                        ]
                    ),
                    0,
                )
            new_slot_payload = json.loads(new_slot.getvalue())
            self.assertEqual(new_slot_payload["status"], "selected")
            new_slot_occurrence_key = new_slot_payload["candidate"]["occurrence_key"]
            self.assertEqual(
                new_slot_occurrence_key,
                f"{RECRUITMENT_FLOW_ID}:cooldown:91.0",
            )
            self.assertNotEqual(new_slot_occurrence_key, accepted_occurrence_key)

            new_slot_duplicate = StringIO()
            with contextlib.redirect_stdout(new_slot_duplicate):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--projection-observed-at-utc",
                            "96",
                            "--projection-next-eligible-at",
                            "91",
                        ]
                    ),
                    0,
                )
            new_slot_duplicate_payload = json.loads(new_slot_duplicate.getvalue())
            self.assertEqual(new_slot_duplicate_payload["status"], "disabled")
            self.assertEqual(
                new_slot_duplicate_payload["reason"],
                "NO_ELIGIBLE_TASK",
            )

            reset_same_slot = StringIO()
            with contextlib.redirect_stdout(reset_same_slot):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--reset-id",
                            "offline-reset-2",
                            "--projection-observed-at-utc",
                            "96",
                            "--projection-next-eligible-at",
                            "91",
                        ]
                    ),
                    0,
                )
            reset_same_slot_payload = json.loads(reset_same_slot.getvalue())
            self.assertEqual(reset_same_slot_payload["status"], "disabled")
            self.assertEqual(
                reset_same_slot_payload["reason"],
                "NO_ELIGIBLE_TASK",
            )
            self.assertNotIn("offline-reset", accepted_occurrence_key)
            self.assertNotIn("offline-reset", new_slot_occurrence_key)


    def test_campaign_pulse_requires_fresh_funded_projection_and_is_restart_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.sqlite3"
            self._enable_sqlite_gates(path, CAMPAIGN_FLOW_ID)
            base = [
                "automation-service",
                "pulse",
                "--state-path",
                str(path),
                "--flow-id",
                CAMPAIGN_FLOW_ID,
                "--now-utc-epoch",
                "100",
                "--health-ok",
                "--projection-observed-at-utc",
                "95",
                "--projection-next-eligible-at",
                "90",
            ]
            underfunded = StringIO()
            with contextlib.redirect_stdout(underfunded):
                self.assertEqual(
                    main(base + ["--projection-observed-balance", "13"]),
                    0,
                )
            underfunded_payload = json.loads(underfunded.getvalue())
            self.assertEqual(underfunded_payload["status"], "disabled")
            self.assertEqual(underfunded_payload["reason"], "NO_ELIGIBLE_TASK")
            self.assertTrue(underfunded_payload["scheduler_eligible"])

            selected = StringIO()
            with contextlib.redirect_stdout(selected):
                self.assertEqual(
                    main(base + ["--projection-observed-balance", "14"]),
                    0,
                )
            payload = json.loads(selected.getvalue())
            self.assertEqual(payload["status"], "selected")
            self.assertEqual(payload["candidate"]["flow_id"], CAMPAIGN_FLOW_ID)
            self.assertEqual(
                payload["result"]["reason_code"],
                "CAMPAIGN_AP_PARENT_CANARY_REQUIRED",
            )
            self.assertEqual(payload["transport_count"], 0)
            self.assertTrue(payload["scheduler_eligible"])
            accepted_occurrence_key = payload["candidate"]["occurrence_key"]
            self.assertTrue(
                accepted_occurrence_key.startswith(
                    f"{CAMPAIGN_FLOW_ID}:ap_regeneration:"
                )
            )
            self.assertNotIn("offline-reset", accepted_occurrence_key)

            duplicate = StringIO()
            with contextlib.redirect_stdout(duplicate):
                self.assertEqual(
                    main(base + ["--projection-observed-balance", "14"]),
                    0,
                )
            duplicate_payload = json.loads(duplicate.getvalue())
            self.assertEqual(duplicate_payload["status"], "disabled")
            self.assertEqual(
                duplicate_payload["reason"],
                "NO_ELIGIBLE_TASK",
            )
            changed_projection = StringIO()
            with contextlib.redirect_stdout(changed_projection):
                self.assertEqual(
                    main(base + ["--projection-observed-balance", "15"]),
                    0,
                )
            changed_payload = json.loads(changed_projection.getvalue())
            self.assertEqual(changed_payload["status"], "selected")
            changed_occurrence_key = changed_payload["candidate"]["occurrence_key"]
            self.assertTrue(
                changed_occurrence_key.startswith(
                    f"{CAMPAIGN_FLOW_ID}:ap_regeneration:"
                )
            )
            self.assertNotEqual(changed_occurrence_key, accepted_occurrence_key)
            self.assertNotIn("offline-reset", changed_occurrence_key)

            reset_same_projection = StringIO()
            with contextlib.redirect_stdout(reset_same_projection):
                self.assertEqual(
                    main(
                        base
                        + [
                            "--reset-id",
                            "offline-reset-2",
                            "--projection-observed-balance",
                            "15",
                        ]
                    ),
                    0,
                )
            reset_same_projection_payload = json.loads(
                reset_same_projection.getvalue()
            )
            self.assertEqual(reset_same_projection_payload["status"], "disabled")
            self.assertEqual(
                reset_same_projection_payload["reason"],
                "NO_ELIGIBLE_TASK",
            )
            self.assertIsNone(reset_same_projection_payload["candidate"])



if __name__ == "__main__":
    unittest.main()
