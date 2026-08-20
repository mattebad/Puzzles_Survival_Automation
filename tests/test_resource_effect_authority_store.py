from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from safe_action_core.resource_effect_authority import (
    ResourceEffectAuthority,
    ResourceOccurrenceIdentity,
    ResourceResetIdentity,
    ResourceFenceError,
)
from safe_action_core.store import SafetyStore, SchemaVersionError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "resource_effect_authority" / "counterfactual_day_d.json"


def _reset(payload: dict) -> ResourceResetIdentity:
    return ResourceResetIdentity(
        payload["reset_identity_id"],
        payload["account_id"],
        payload["server_id"],
        payload["runtime_scope"],
        payload["reset_start_utc"],
        payload["reset_deadline_utc"],
        observed_at=1.0,
        evidence_refs=("fixture:counterfactual",),
    )


class ResourceAuthorityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "resource.sqlite3"
        self.store = SafetyStore(self.path)
        self.authority = ResourceEffectAuthority(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_fresh_schema_is_v4_and_resource_tables_are_additive(self) -> None:
        self.assertEqual(self.store.schema_version, 4)
        self.assertTrue(
            self.store.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='actions'"
            ).fetchone()
        )
        self.assertTrue(
            self.store.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='resource_occurrences'"
            ).fetchone()
        )

    def test_future_schema_remains_fail_closed(self) -> None:
        path = Path(self.temp.name) / "future.sqlite3"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE schema_version(singleton INTEGER PRIMARY KEY, version INTEGER)")
        db.execute("INSERT INTO schema_version VALUES(1, 99)")
        db.commit()
        db.close()
        with self.assertRaises(SchemaVersionError):
            SafetyStore(path)

    def test_v3_rows_survive_additive_reopen(self) -> None:
        self.store.connection.execute(
            """INSERT INTO task_state(
                task_id,completion_key,game_day_id,status,next_due_monotonic,
                revision,last_reason,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            ("task", "completion", "day", "pending", None, 0, "", 1.0),
        )
        self.store.connection.execute(
            """INSERT INTO scheduler_invocation_state(
                account_id,server_id,reset_id,task_id,status,next_eligible_at,
                revision,last_reason_code,observed_progress_json,action_count_total,
                unresolved_action,evidence_refs_json,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("account", "server", "reset", "task", "pending", None, 0, "", "{}", 0, 0, "[]", 1.0),
        )
        self.store.connection.commit()
        self.store.connection.execute("UPDATE schema_version SET version=3 WHERE singleton=1")
        self.store.close()
        self.store = SafetyStore(self.path)
        self.assertEqual(self.store.schema_version, 4)
        self.assertIsNotNone(self.store.get_task_state("task"))
        self.assertIsNotNone(
            self.store.get_scheduler_invocation_state("account", "server", "reset", "task")
        )

    def test_occurrence_identity_contains_reset_and_is_revision_metadata_only(self) -> None:
        self.authority.append_reset_identity(
            ResourceResetIdentity(
                "reset-D",
                "account",
                "server",
                "scope",
                "2026-08-19T00:00:00Z",
                "2026-08-20T00:00:00Z",
                observed_at=1.0,
                evidence_refs=("fixture:reset-D",),
            )
        )
        first = self.authority.create_resource_occurrence(
            ResourceOccurrenceIdentity(
                "account",
                "server",
                "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
                "reset-D",
            )
        )
        self.assertTrue(first["occurrence_key"].startswith("occ:v1:"))
        self.assertIn("reset-D", self.authority.occurrence_context(first["occurrence_id"]).canonical_identity())
        changed_revision = ResourceOccurrenceIdentity(
            "account",
            "server",
            "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
            "reset-D",
            product_policy_revision="different-revision",
        )
        self.assertEqual(first["occurrence_key"], changed_revision.occurrence_key())

    def test_counterfactual_d_denies_completed_occurrence_and_d_plus_1_is_distinct(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        d = fixture["day_d"]
        d1 = fixture["day_d_plus_1"]
        self.authority.append_reset_identity(_reset(d))
        self.authority.append_reset_identity(_reset(d1))
        occurrence_d = self.authority.create_resource_occurrence(
            ResourceOccurrenceIdentity(
                d["account_id"],
                d["server_id"],
                "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
                d["reset_identity_id"],
            )
        )
        occurrence_d1 = self.authority.create_resource_occurrence(
            ResourceOccurrenceIdentity(
                d1["account_id"],
                d1["server_id"],
                "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
                d1["reset_identity_id"],
            )
        )
        self.authority._cas_occurrence(
            self.store.connection,
            occurrence_id=occurrence_d["occurrence_id"],
            expected_states={"ELIGIBLE"},
            next_state="COMPLETED",
            now=2.0,
            reason="counterfactual_confirmed_effect",
        )
        denied = self.authority.claim_resource_attempt(
            occurrence_d["occurrence_id"], "owner", now=3.0
        )
        self.assertEqual(denied.state, "DENIED")
        self.assertFalse(denied.can_dispatch)
        eligible = self.authority.claim_resource_attempt(
            occurrence_d1["occurrence_id"], "owner", now=3.0
        )
        self.assertEqual(eligible.state, "ACTIVE")
        self.assertNotEqual(occurrence_d["occurrence_key"], occurrence_d1["occurrence_key"])

    def test_changed_hypothesis_allows_only_proven_no_effect_before_confirmation(self) -> None:
        self.authority.append_reset_identity(
            ResourceResetIdentity(
                "reset-retry",
                "account",
                "server",
                "scope",
                "2026-08-19T00:00:00Z",
                "2026-08-20T00:00:00Z",
                observed_at=1.0,
                evidence_refs=("fixture:retry",),
            )
        )
        occurrence = self.authority.create_resource_occurrence(
            ResourceOccurrenceIdentity(
                "account",
                "server",
                "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
                "reset-retry",
            ),
            now=1.0,
        )
        occurrence_id = occurrence["occurrence_id"]
        self.authority._cas_occurrence(
            self.store.connection,
            occurrence_id=occurrence_id,
            expected_states={"ELIGIBLE"},
            next_state="NO_EFFECT",
            now=2.0,
            reason="test_proven_no_effect",
        )
        first_attempt_id = self.authority._insert_attempt(
            self.store.connection,
            occurrence_id=occurrence_id,
            generation=1,
            state="NO_EFFECT",
            owner_id="owner",
            hypothesis_digest="hypothesis-1",
            now=2.0,
        )
        context = self.authority.occurrence_context(occurrence_id)
        self.store.connection.execute(
            """
            INSERT INTO actions(
                action_id,action_key,task_id,semantic_action,source_state,
                target_identity,target_roi_json,source_frame_sha256,
                source_frame_captured_at,runtime_profile_id,game_day_id,
                expected_postcondition,consequence,cost_type,cost_amount,
                quantity,consequential,policy_request_json,policy_decision,
                policy_reason,prepared_at,evidence_refs_json,final_status,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "action-retry",
                "action-key-retry",
                "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION",
                "USE_RESOURCE_ITEM",
                "RESOURCES_1K_FOOD_READY",
                "daily-resource-item:use-1k-food",
                "[1,2,3,4]",
                "a" * 64,
                1.0,
                "pns-bluestacks-5-p64-800x1280-v1",
                "reset-retry",
                "RESOURCES_1K_FOOD_USED",
                "ordinary_non_idempotent_resource_item_use",
                "owned_inventory_item",
                1,
                1,
                0,
                "{}",
                "authorize",
                "test",
                1.0,
                "[]",
                "cancelled",
                1.0,
            ),
        )
        self.store.connection.execute(
            """
            INSERT INTO resource_reservations(
                reservation_id,occurrence_id,attempt_id,action_id,effect_ordinal,
                authorization_generation,state,state_revision,account_id,server_id,
                reset_identity_id,product_policy_revision,recurrence_policy_revision,
                authorization_context_digest,claim_token_digest,claim_epoch,
                controller_token_digest,controller_generation,runtime_invocation_id,
                immediate_before_sha256,created_at,updated_at,content_digest,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "reservation-retry",
                occurrence_id,
                first_attempt_id,
                "action-retry",
                1,
                1,
                "NO_EFFECT_CONFIRMED",
                2,
                "account",
                "server",
                "reset-retry",
                context.product_policy_revision,
                context.recurrence_policy_revision,
                context.digest(),
                "b" * 64,
                1,
                "c" * 64,
                1,
                "retry-invocation",
                "d" * 64,
                1.0,
                2.0,
                "e" * 64,
                "{}",
            ),
        )
        self.store.connection.execute(
            """
            INSERT INTO resource_transport_facts(
                transport_fact_id,reservation_id,occurrence_id,attempt_id,
                account_id,server_id,state,runtime_invocation_id,adapter_invoked,
                transport_result_json,recorded_at,content_digest,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "transport-retry",
                "reservation-retry",
                occurrence_id,
                first_attempt_id,
                "account",
                "server",
                "TRANSPORT_UNKNOWN",
                "retry-invocation",
                1,
                '{"transport_code":"UNKNOWN"}',
                2.0,
                "f" * 64,
                "{}",
            ),
        )
        self.store.connection.execute(
            """
            INSERT INTO resource_transport_outcomes(
                outcome_id,transport_fact_id,reservation_id,occurrence_id,attempt_id,
                account_id,server_id,runtime_invocation_id,state,adapter_invoked,
                result_json,result_digest,recorded_at,content_digest,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "outcome-retry",
                "transport-retry",
                "reservation-retry",
                occurrence_id,
                first_attempt_id,
                "account",
                "server",
                "retry-invocation",
                "TRANSPORT_UNKNOWN",
                1,
                '{"transport_code":"UNKNOWN"}',
                "1" * 64,
                2.0,
                "2" * 64,
                "{}",
            ),
        )
        self.store.connection.execute(
            """
            INSERT INTO resource_live_effects(
                live_effect_id,reservation_id,transport_fact_id,occurrence_id,
                attempt_id,account_id,server_id,effect_ordinal,effect_state,
                before_owned_quantity,after_owned_quantity,evidence_refs_json,
                created_at,content_digest,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "effect-no-effect",
                "reservation-retry",
                "transport-retry",
                occurrence_id,
                first_attempt_id,
                "account",
                "server",
                1,
                "NO_EFFECT",
                2,
                2,
                "[]",
                2.0,
                "3" * 64,
                json.dumps({"effect_state": "NO_EFFECT", "proven_no_effect": True}),
            ),
        )
        self.store.connection.commit()

        identical = self.authority.claim_resource_attempt(
            occurrence_id,
            "owner",
            now=3.0,
            hypothesis_digest="hypothesis-1",
        )
        self.assertEqual(identical.state, "DENIED")
        changed = self.authority.claim_resource_attempt(
            occurrence_id,
            "owner",
            now=4.0,
            hypothesis_digest="hypothesis-2",
        )
        self.assertEqual(changed.state, "ACTIVE")
        self.store.connection.execute(
            "UPDATE resource_attempt_claims SET state='EXPIRED' WHERE claim_id=?",
            (changed.claim_id,),
        )
        self.store.connection.execute(
            """
            INSERT INTO resource_live_effects(
                live_effect_id,reservation_id,transport_fact_id,occurrence_id,
                attempt_id,account_id,server_id,effect_ordinal,effect_state,
                before_owned_quantity,after_owned_quantity,evidence_refs_json,
                created_at,content_digest,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "effect-confirmed",
                "reservation-retry",
                "transport-retry",
                occurrence_id,
                first_attempt_id,
                "account",
                "server",
                1,
                "CONFIRMED",
                2,
                1,
                "[]",
                5.0,
                "4" * 64,
                json.dumps({"effect_state": "CONFIRMED"}),
            ),
        )
        self.store.connection.commit()
        later = self.authority.claim_resource_attempt(
            occurrence_id,
            "owner",
            now=6.0,
            hypothesis_digest="hypothesis-3",
        )
        self.assertEqual(later.state, "DENIED")
        self.assertFalse(later.can_dispatch)

    def test_projection_relationships_and_cas_fail_closed(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.connection.execute(
                """INSERT INTO resource_terminal_projection(
                    occurrence_id,observation_id,terminal_state,state_revision,updated_at
                ) VALUES('missing','missing','HOME_CANONICAL',0,0)"""
            )
        with self.assertRaises(ResourceFenceError):
            self.authority.append_reset_binding_assertion(
                {
                    "effect_kind": "historical",
                    "effect_id": "effect",
                    "assertion_state": "UNRESOLVED",
                    "assertion_id": "assertion",
                }
            )
            self.authority.append_reset_binding_assertion(
                {
                    "effect_kind": "historical",
                    "effect_id": "effect",
                    "assertion_state": "UNRESOLVED",
                    "assertion_id": "assertion",
                },
                expected_projection_revision=3,
            )

    def test_resource_facts_cannot_be_deleted(self) -> None:
        self.authority.append_reset_identity(
            ResourceResetIdentity(
                "reset",
                "account",
                "server",
                "scope",
                "2026-08-19T00:00:00Z",
                "2026-08-20T00:00:00Z",
                observed_at=1.0,
                evidence_refs=("fixture",),
            )
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.connection.execute(
                "DELETE FROM resource_reset_identities WHERE reset_identity_id='reset'"
            )


if __name__ == "__main__":
    unittest.main()
