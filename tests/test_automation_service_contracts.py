from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from automation_service import (
    CostEffectVector,
    FamilyFacts,
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    PerceptionEnvelope,
    SchedulerFacts,
    SemanticActionIntent,
)
from automation_service.registry import (
    ENTRY_FIELDS,
    NOVA_FLOW_ID,
    NOVA_HANDLER_ID,
    NOVA_PHASE_MODE,
    NOVA_PRODUCT_ID,
    NOVA_PRODUCT_REVISION,
    NOVA_PROFILE_ID,
    RegisteredDispatchSnapshot,
    WORLD_FLOW_ID,
    WORLD_HANDLER_ID,
    WORLD_PHASE_MODE,
    WORLD_PRODUCT_ID,
    WORLD_PRODUCT_REVISION,
    WORLD_PROFILE_ID,
    consume_nova_registration,
    consume_registered_entry,
    load_disabled_registry,
)
from scripts.pnsctl import BLUESTACKS_FLOW_IDS


ROOT = Path(__file__).resolve().parents[1]

def nova_registered_registry_payload() -> dict:
    payload = json.loads(
        (
            ROOT / "tasks" / "flow_delivery_disabled_production_registry.json"
        ).read_text(encoding="utf-8")
    )
    payload["flows"][NOVA_FLOW_ID] = {
        "mode": NOVA_PHASE_MODE,
        "product_id": NOVA_PRODUCT_ID,
        "product_revision": NOVA_PRODUCT_REVISION,
        "production_handler": NOVA_HANDLER_ID,
        "profile": NOVA_PROFILE_ID,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
        "supported_profiles": [NOVA_PROFILE_ID],
    }
    return payload



class AutomationServiceContractTests(unittest.TestCase):
    def test_typed_contracts_preserve_separate_facts_and_cost_dimensions(self) -> None:
        descriptor = FlowDescriptor("flow", "owner", "family", "variant", "daily_once")
        facts = PerceptionEnvelope(
            "capture-1",
            "home_canonical",
            "profile",
            "fresh",
            family_facts=(FamilyFacts("campaign", True, {"destination": "1-20-9"}),),
        )
        cost = CostEffectVector(
            resource={"food": -10},
            currency={"premium": 0},
            ap=0,
            reserve={"food": 100},
            cap={"ap": 120},
        )
        intent = SemanticActionIntent(
            "navigate_campaign",
            "flow",
            "home_canonical",
            "campaign_destination_recognized",
            cost,
        )
        self.assertEqual(descriptor.family, "family")
        self.assertFalse(descriptor.scheduler_eligible)
        self.assertEqual(facts.facts_for("campaign").values["destination"], "1-20-9")
        self.assertEqual(intent.cost_effect.to_mapping()["resource"]["food"], -10)
        self.assertEqual(intent.action_key, "flow:navigate_campaign")

    def test_normalized_outcomes_have_scheduler_vocabulary(self) -> None:
        result = NormalizedResult(
            NormalizedOutcome.DEFERRED,
            "COOLDOWN",
            next_eligible_at=123.0,
        )
        self.assertEqual(result.outcome.value, "deferred")
        self.assertFalse(SchedulerFacts("a", "s", "r", 123.0).health_ok)
        self.assertEqual(
            SchedulerFacts("a", "s", "r", 123.0, health_ok=True).now_utc_epoch,
            123.0,
        )

    def test_unresolved_normalizes_to_global_block(self) -> None:
        result = NormalizedResult(NormalizedOutcome.UNRESOLVED, "UNKNOWN_RESULT")
        self.assertTrue(result.unresolved_action)

    def test_registry_closure_disables_every_exact_binding(self) -> None:
        entries = load_disabled_registry()
        self.assertTrue(entries)
        payload = json.loads(
            (
                ROOT / "tasks" / "flow_delivery_disabled_production_registry.json"
            ).read_text(encoding="utf-8")
        )
        for value in payload["flows"].values():
            self.assertEqual(set(value), ENTRY_FIELDS)
        self.assertFalse(any(item.registered for item in entries))
        self.assertTrue(all(item.mode == "disabled" for item in entries))
        self.assertTrue(
            all(item.registration_status == "NOT_REGISTERED" for item in entries)
        )
        self.assertTrue(all(item.scheduler_eligible is False for item in entries))
        registry_ids = {item.flow_id for item in entries}
        self.assertEqual(
            registry_ids,
            set(BLUESTACKS_FLOW_IDS) | {"RECRUITMENT-BLUESTACKS-INTEGRATION"},
        )

    def test_snapshot_allowlist_and_registry_cardinality_are_strict(self) -> None:
        snapshot = RegisteredDispatchSnapshot(
            NOVA_FLOW_ID,
            NOVA_PRODUCT_ID,
            NOVA_PRODUCT_REVISION,
            NOVA_HANDLER_ID,
            NOVA_PROFILE_ID,
            NOVA_PHASE_MODE,
            "REGISTERED",
            True,
        )
        self.assertEqual(
            RegisteredDispatchSnapshot.from_mapping(snapshot.to_mapping()),
            snapshot,
        )
        forged = snapshot.to_mapping()
        forged["product_id"] = WORLD_PRODUCT_ID
        with self.assertRaises(ValueError):
            RegisteredDispatchSnapshot.from_mapping(forged)
        with self.assertRaises(ValueError):
            RegisteredDispatchSnapshot.from_mapping(
                {**snapshot.to_mapping(), "extra": "forged"}
            )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            payload = nova_registered_registry_payload()
            payload["flows"][WORLD_FLOW_ID] = {
                "mode": WORLD_PHASE_MODE,
                "product_id": WORLD_PRODUCT_ID,
                "product_revision": WORLD_PRODUCT_REVISION,
                "production_handler": WORLD_HANDLER_ID,
                "profile": WORLD_PROFILE_ID,
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
                "supported_profiles": [WORLD_PROFILE_ID],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at most one"):
                load_disabled_registry(path)

    def test_atomic_nova_consumption_returns_snapshot_and_closes_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(
                json.dumps(nova_registered_registry_payload()), encoding="utf-8"
            )
            snapshot = consume_registered_entry(NOVA_FLOW_ID, path=path)
            self.assertIsInstance(snapshot, RegisteredDispatchSnapshot)
            self.assertEqual(snapshot.flow_id, NOVA_FLOW_ID)
            self.assertIsNone(consume_registered_entry(NOVA_FLOW_ID, path=path))
            self.assertFalse(any(item.registered for item in load_disabled_registry(path)))

    def test_nova_wrapper_consumes_nova_not_world_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(
                json.dumps(nova_registered_registry_payload()), encoding="utf-8"
            )

            snapshot = consume_nova_registration(path=path)

            self.assertIsInstance(snapshot, RegisteredDispatchSnapshot)
            self.assertEqual(snapshot.flow_id, NOVA_FLOW_ID)
            world = next(
                item
                for item in load_disabled_registry(path)
                if item.flow_id == WORLD_FLOW_ID
            )
            self.assertFalse(world.registered)


if __name__ == "__main__":
    unittest.main()
