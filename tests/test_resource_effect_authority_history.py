from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from safe_action_core.resource_effect_authority import (
    HistoricalResourceEffect,
    HistoricalResourceTransportFact,
    ResourceEffectAuthority,
    ResourceIntegrityError,
    ResourceResetIdentity,
)
from safe_action_core.store import SafetyStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "resource_effect_authority" / "historical_sessions.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ResourceAuthorityHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = SafetyStore(Path(self.temp.name) / "history.sqlite3")
        self.authority = ResourceEffectAuthority(self.store)
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def _import_fixture(self) -> list[dict]:
        effects = []
        for session in self.fixture["sessions"]:
            self.assertEqual(_digest(Path(session["summary"]["path"])), session["summary"]["sha256"])
            self.assertEqual(_digest(Path(session["events"]["path"])), session["events"]["sha256"])
            transport = self.authority.import_historical_resource_transport(
                HistoricalResourceTransportFact(
                    historical_session_id=session["session_id"],
                    action_key=session["action_key"],
                    transport_at_utc=session["transport_at_utc"],
                    source_frame_sha256=session["transport_source_frame"]["sha256"],
                    transport_result={"dispatched": True, "transport_code": "native_tap"},
                    unknown_fields=tuple(session["unknown_fields"]),
                    evidence_refs=(
                        session["events"]["path"],
                        session["transport_source_frame"]["path"],
                        session["settled_post"]["path"],
                    ),
                )
            )
            effect = self.authority.import_historical_resource_effect(
                HistoricalResourceEffect(
                    historical_session_id=session["session_id"],
                    transport_fact_id=transport["transport_fact_id"],
                    before_owned_quantity=session["owned_quantity"]["before"],
                    after_owned_quantity=session["owned_quantity"]["after"],
                    effect_state="CONFIRMED" if session["terminal_state"] == "home" else "UNRESOLVED",
                    unknown_fields=tuple(session["unknown_fields"]),
                )
            )
            effects.append(effect)
        return effects

    def test_both_retained_decrements_are_distinct_immutable_facts(self) -> None:
        effects = self._import_fixture()
        self.assertEqual(len(effects), 2)
        self.assertEqual(
            [(row["before_owned_quantity"], row["after_owned_quantity"]) for row in effects],
            [(129681, 129680), (129680, 129679)],
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) AS count FROM resource_historical_transport_facts"
            ).fetchone()["count"],
            2,
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) AS count FROM resource_historical_effects"
            ).fetchone()["count"],
            2,
        )
        classifications = self.store.connection.execute(
            "SELECT DISTINCT classification_code FROM resource_historical_classifications"
        ).fetchall()
        self.assertEqual([row["classification_code"] for row in classifications], ["SUSPECTED_SAME_CYCLE_DUPLICATE"])
        self.assertTrue(
            self.authority.has_scoped_resource_block(
                {"scope_key": "runtime-objective:unknown|use_resource_item"}
            )
        )

    def test_exact_fixture_importer_reads_only_named_paths(self) -> None:
        imported = self.authority.import_historical_sessions(FIXTURE)
        self.assertEqual(len(imported["transports"]), 2)
        self.assertEqual(len(imported["effects"]), 2)
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) AS count FROM resource_historical_effects"
            ).fetchone()["count"],
            2,
        )

    def test_reimport_is_idempotent_and_payload_mismatch_is_integrity_error(self) -> None:
        effects = self._import_fixture()
        first = self.fixture["sessions"][0]
        transport = self.authority.import_historical_resource_transport(
            HistoricalResourceTransportFact(
                historical_session_id=first["session_id"],
                action_key=first["action_key"],
                transport_at_utc=first["transport_at_utc"],
                source_frame_sha256=first["transport_source_frame"]["sha256"],
                transport_result={"dispatched": True, "transport_code": "native_tap"},
                unknown_fields=tuple(first["unknown_fields"]),
                evidence_refs=(
                    first["events"]["path"],
                    first["transport_source_frame"]["path"],
                    first["settled_post"]["path"],
                ),
            )
        )
        self.assertEqual(transport["transport_fact_id"], effects[0]["transport_fact_id"])
        with self.assertRaises(ResourceIntegrityError):
            self.authority.import_historical_resource_effect(
                HistoricalResourceEffect(
                    historical_session_id=first["session_id"],
                    transport_fact_id=transport["transport_fact_id"],
                    before_owned_quantity=129681,
                    after_owned_quantity=129678,
                    effect_state="UNRESOLVED",
                    historical_effect_id=effects[0]["historical_effect_id"],
                )
            )

    def test_later_reset_clears_only_future_scope_and_conflict_reactivates_block(self) -> None:
        self._import_fixture()
        later = ResourceResetIdentity(
            "reset-later",
            "account",
            "server",
            "unknown",
            "2026-08-20T00:00:01Z",
            "2026-08-21T00:00:00Z",
            observed_at=10.0,
            evidence_refs=("fixture:later-reset",),
        )
        self.authority.append_reset_identity(later)
        block = self.store.connection.execute(
            "SELECT block_id FROM resource_effect_block_facts LIMIT 1"
        ).fetchone()["block_id"]
        cleared = self.authority.append_historical_block_resolution(
            {
                "block_id": block,
                "decision": "CLEAR_FOR_PROVEN_LATER_RESET",
                "current_reset_id": "reset-later",
                "authoritative_evidence": {
                    "account_id": "account",
                    "server_id": "server",
                    "evidence_refs": ["fixture:later-reset"],
                },
            }
        )
        self.assertEqual(cleared["projection_state"], "CLEARED")
        self.assertFalse(
            self.authority.has_scoped_resource_block(
                {
                    "scope_key": "runtime-objective:unknown|use_resource_item",
                    "reset_identity_id": "reset-later",
                }
            )
        )
        self.assertTrue(
            self.authority.has_scoped_resource_block(
                {"scope_key": "runtime-objective:unknown|use_resource_item"}
            )
        )
        conflict = self.authority.append_historical_block_resolution(
            {
                "block_id": block,
                "decision": "CONFLICT",
                "authoritative_evidence": {"evidence_refs": ["fixture:conflict"]},
            }
        )
        self.assertEqual(conflict["projection_state"], "ACTIVE")
        self.assertTrue(
            self.authority.has_scoped_resource_block(
                {
                    "scope_key": "runtime-objective:unknown|use_resource_item",
                    "reset_identity_id": "reset-later",
                }
            )
        )

    def test_terminal_observation_projection_is_same_occurrence_and_append_only(self) -> None:
        self._import_fixture()
        # Historical facts remain independent; use a synthetic occurrence only
        # to prove the terminal projection relationship.
        self.authority.append_reset_identity(
            ResourceResetIdentity(
                "term-reset",
                "term-account",
                "term-server",
                "term-scope",
                "2026-08-19T00:00:00Z",
                "2026-08-20T00:00:00Z",
                observed_at=1.0,
                evidence_refs=("fixture:terminal",),
            )
        )
        occurrence_id = self.authority.create_resource_occurrence(
            {
                "account_id": "term-account",
                "server_id": "term-server",
                "reset_identity_id": "term-reset",
            }
        )["occurrence_id"]
        self.store.connection.execute(
            """INSERT INTO resource_terminal_observations(
                observation_id,occurrence_id,terminal_state,frame_sha256,
                evidence_refs_json,content_digest,payload_json
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "observation",
                occurrence_id,
                "HOME_CANONICAL",
                "a" * 64,
                "[]",
                "b" * 64,
                "{}",
            ),
        )
        # The foreign key correctly rejects a projection whose source
        # observation is from another occurrence.
        with self.assertRaises(Exception):
            self.store.connection.execute(
                """INSERT INTO resource_terminal_projection(
                    occurrence_id,observation_id,terminal_state,state_revision,updated_at
                ) VALUES(?,?,?,?,?)""",
                ("other-occurrence", "observation", "HOME_CANONICAL", 0, 0.0),
            )


if __name__ == "__main__":
    unittest.main()
