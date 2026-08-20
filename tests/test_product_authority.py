"""Focused tests for schema-v2 product authority and representative bindings."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.generate_flow_authority_views import (
    AuthorityViewError,
    build_authority_view,
    check_authority_view,
    write_authority_view,
)
from tasks.gameplay_flow_contracts import load_all_flow_contracts
from tasks.product_authority import (
    AUTHORITY_REVISION,
    ProductAuthorityError,
    authority_digest,
    canonical_digest,
    load_product_authority,
    record_digest,
    validate_contract_product_authority_bindings,
    validate_product_authority,
)


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = ROOT / "tasks" / "flow_delivery_product_policy.json"


class ProductAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = load_product_authority()
        self.contracts = load_all_flow_contracts()
        self.records = {
            record["record_id"]: record
            for record in self.authority["product_records"]
        }

    def test_authority_is_v2_and_has_exactly_three_typed_records(self) -> None:
        self.assertEqual(self.authority["schema_version"], 2)
        self.assertEqual(self.authority["authority_revision"], AUTHORITY_REVISION)
        self.assertEqual(
            set(self.records),
            {"use_resource_item", "enhancement_family", "supply_depot"},
        )
        validate_product_authority(self.authority)

    def test_digest_excludes_only_its_own_field(self) -> None:
        first = {"a": 1, "digest": "0" * 64}
        second = {"a": 1, "digest": "f" * 64}
        self.assertEqual(canonical_digest(first), canonical_digest(second))
        record = deepcopy(self.records["use_resource_item"])
        self.assertEqual(record_digest(record), record["record_digest"])
        self.assertEqual(authority_digest(self.authority), self.authority["authority_digest"])

    def test_resource_semantics_are_direct_owned_one_item(self) -> None:
        record = self.records["use_resource_item"]
        self.assertEqual(record["objective"], "use_resource_item")
        self.assertEqual(
            record["semantic_entry_route"]["source_home_authorities"],
            ["HOME_READY", "HOME_CANONICAL"],
        )
        self.assertEqual(record["semantic_entry_route"]["target"], "BAG")
        self.assertEqual(record["target"]["item_name"], "1K Food")
        self.assertTrue(record["target"]["owned"])
        self.assertEqual(record["quantity_cost"]["quantity"], 1)
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 1)
        self.assertFalse(record["quantity_cost"]["cost"]["free_only"])
        self.assertEqual(record["semantic_effect"]["effect_ordinal"], 1)
        self.assertFalse(record["daily_ownership"]["selected_daily_prerequisite"])

    def test_enhancement_semantics_separate_use_and_confirm(self) -> None:
        record = self.records["enhancement_family"]
        self.assertEqual(record["target"]["variants"], ["Gear", "Chip", "Module"])
        self.assertTrue(record["target"]["independent"])
        actions = {item["action_id"]: item for item in record["actions"]}
        self.assertFalse(actions["quantity_selection_use"]["consumes_material"])
        self.assertFalse(actions["quantity_selection_use"]["owns_material_decrement"])
        self.assertTrue(actions["consuming_confirm"]["consumes_material"])
        self.assertTrue(actions["consuming_confirm"]["owns_material_decrement"])
        forbidden = json.dumps(record["forbidden_actions"]).casefold()
        for marker in ("auto select", "higher-star", "premium", "unknown", "real-money"):
            self.assertIn(marker, forbidden)

    def test_supply_semantics_are_free_evidence_only(self) -> None:
        record = self.records["supply_depot"]
        self.assertEqual(record["semantic_entry_route"]["target"], "SUPPLY_DEPOT")
        self.assertEqual(record["target"]["free_control"], "Free")
        self.assertEqual(record["quantity_cost"]["cost"]["amount"], 0)
        self.assertTrue(record["quantity_cost"]["cost"]["free_only"])
        self.assertFalse(record["semantic_effect"]["paid_collection"])
        self.assertEqual(record["daily_ownership"]["daily_owner"], None)
        self.assertNotIn("daily 5/5", json.dumps(record["semantic_effect"]).casefold())

    def test_product_records_have_no_forbidden_authority_domains(self) -> None:
        forbidden = {
            "coordinate",
            "coordinates",
            "ocr",
            "profile",
            "profile_id",
            "runtime",
            "runtime_binding",
            "runtime_profile",
            "proof",
            "proof_state",
            "status",
            "queue",
            "registration",
            "scheduler",
            "conductor",
            "plan",
            "backlog",
        }

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield str(key).casefold().replace("-", "_")
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        for record in self.records.values():
            self.assertTrue(forbidden.isdisjoint(set(keys(record))))

    def test_all_three_representative_contracts_bind_exact_authority(self) -> None:
        validate_contract_product_authority_bindings(self.authority, self.contracts)
        bound = {
            contract["product_authority_binding"]["product_record_id"]
            for contract in self.contracts.values()
            if "product_authority_binding" in contract
        }
        self.assertEqual(bound, set(self.records))

    def test_stale_revision_or_digest_fails_closed(self) -> None:
        stale_revision = deepcopy(self.authority)
        stale_revision["authority_revision"] = "old-authority-revision"
        with self.assertRaises(ProductAuthorityError):
            validate_product_authority(stale_revision)

        stale_payload = deepcopy(self.authority)
        stale_payload["policies"][0]["decision"] += " changed"
        with self.assertRaisesRegex(ProductAuthorityError, "stale product authority digest"):
            validate_product_authority(stale_payload)

        stale_record = deepcopy(self.authority)
        stale_record["product_records"][0]["purpose"] += " changed"
        stale_record["authority_digest"] = authority_digest(stale_record)
        with self.assertRaisesRegex(ProductAuthorityError, "stale record digest"):
            validate_product_authority(stale_record)

    def test_selected_daily_generic_home_and_bliss_mutations_fail(self) -> None:
        contract = self.contracts["DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"]

        selected_daily = deepcopy(contract)
        selected_daily["scenarios"][0]["permitted_inputs"].append(
            "open selected Daily"
        )
        with self.assertRaises(ProductAuthorityError):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": selected_daily},
            )

        generic_home = deepcopy(contract)
        generic_home["product_authority_binding"]["home_authority"] = "Home"
        with self.assertRaises(ProductAuthorityError):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": generic_home},
            )

        generic_home_state = deepcopy(contract)
        generic_home_state["transition_contracts"][0]["from"] = "hOmE"
        with self.assertRaisesRegex(ProductAuthorityError, "generic Home state"):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": generic_home_state},
            )

        bliss = deepcopy(contract)
        bliss["product_authority_binding"]["platform"] = "bliss"
        with self.assertRaises(ProductAuthorityError):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": bliss},
            )

    def test_binding_requires_exact_native_profile_and_package(self) -> None:
        contract = self.contracts["DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"]

        extra_binding_id = deepcopy(contract)
        extra_binding_id["product_authority_binding"]["platform_binding_ids"].append(
            "arbitrary-binding-id"
        )
        with self.assertRaisesRegex(ProductAuthorityError, "exact BlueStacks binding set"):
            validate_contract_product_authority_bindings(
                self.authority,
                {"resource": extra_binding_id},
            )

        for field in ("platform_profile_id", "package_id"):
            omitted = deepcopy(contract)
            omitted["product_authority_binding"].pop(field)
            with self.subTest(field=field), self.assertRaises(ProductAuthorityError):
                validate_contract_product_authority_bindings(
                    self.authority,
                    {"resource": omitted},
                )

    def test_generated_view_is_deterministic_and_detects_tamper(self) -> None:
        view = build_authority_view()
        supply = next(
            item
            for item in view["bound_flows"]
            if item["flow_id"] == "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION"
        )
        supply_text = json.dumps(supply).casefold()
        self.assertNotIn("daily 5/5", supply_text)
        self.assertNotIn("collect", supply_text)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "authority-view.json"
            write_authority_view(output)
            first = output.read_text(encoding="utf-8")
            check_authority_view(output)
            write_authority_view(output)
            self.assertEqual(first, output.read_text(encoding="utf-8"))

            payload = json.loads(first)
            payload["bound_flows"][0]["flow_id"] = "tampered"
            output.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(AuthorityViewError, "stale or hand-edited"):
                check_authority_view(output)


if __name__ == "__main__":
    unittest.main()
