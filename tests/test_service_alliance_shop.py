from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from automation_service.alliance_shop import (
    AllianceShopRunner,
    MAX_ACTIONS,
    MAX_INPUTS,
    alliance_shop_next_due,
)
from automation_service.native_execution import NativeRouteOutcome, NativeRouteRequest
from automation_service.registry import (
    ALLIANCE_SHOP_FLOW_ID,
    ALLIANCE_SHOP_PRODUCT_ID,
    ALLIANCE_SHOP_PRODUCT_REVISION,
)
from automation_service.recruitment import recruitment_reset
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity
from safe_action_core import SafetyStore
from scripts.alliance_shop_bluestacks import AllianceShopPurchaseRoute
from tasks.purchases_disabled import canonical_purchase_action_key
from tests.test_alliance_shop_bluestacks import ActualSafetyStoreAlliancePort
from tests.test_daily_shops_bluestacks import safety_store_purchase_context


class FakeRuntimeInputLock:
    owner = "automation-service"
    invocation_id = "alliance-shop-service-invocation"
    held = True

    def assert_held(self, owner, invocation_id):
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise AssertionError("Alliance Shop runtime owner changed")


class FakeNativeBoundary:
    flow_id = ALLIANCE_SHOP_FLOW_ID
    product_id = ALLIANCE_SHOP_PRODUCT_ID
    product_revision = ALLIANCE_SHOP_PRODUCT_REVISION
    runtime_profile_id = ACTIVE_RUNTIME_PROFILE_ID
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, result, *, failure=None, count=7, accounting=True):
        self.result, self.failure, self.count, self.accounting = result, failure, count, accounting
        self.request = None

    def run(self, request: NativeRouteRequest):
        self.request = request
        return NativeRouteOutcome(
            flow_id=ALLIANCE_SHOP_FLOW_ID,
            native_result=self.result,
            partial_result=None,
            failure=self.failure,
            invocation_id=FakeRuntimeInputLock.invocation_id,
            session_directory="/synthetic/alliance-shop",
            startup_recovery=None,
            input_count=self.count,
            session_input_count=self.count,
            runtime_input_count=self.count,
            accounting_verified=self.accounting,
        )


def native_result(**overrides):
    result = {
        "status": "completed",
        "reason": "ALLIANCE_ALLOWLISTED_PURCHASE_AND_HOME_VERIFIED",
        "purchase_transport_calls": 1,
        "committed_action_count": 1,
        "prior_confirmed_action_count": 0,
        "accounting_verified": True,
        "total_input_count": 7,
        "terminal_home_verified": True,
        "offer_effect_verified": True,
        "selected_offer": {
            "shop_identity": "Weekly Offers", "offer_identity": "weekly:bioenhance-scheme",
            "item_identity": "Bioenhance Scheme", "currency_identity": "Alliance Coins",
            "rarity": None, "unit_price": 80000, "balance_before": 100000,
            "stock_before": 2, "item_quantity_before": 0, "quantity": 1, "total": 80000,
        },
        "selection_evidence": {
            "weekly_inventory": {
                "complete": True, "reason": "",
                "frame_refs": ("weekly-page.png",), "frame_sha256s": ("b" * 64,),
            },
            "weekly_offers": ({
                "shop_identity": "Weekly Offers", "item_identity": "Bioenhance Scheme",
                "currency_identity": "Alliance Coins", "unit_price": 80000,
                "balance": 100000, "stock": 2, "rarity": None, "available": True,
                "premium": False, "recognized": True, "offer_identity": "weekly:bioenhance-scheme",
            },),
            "fallback_inventory": None,
            "fallback_offer": None,
        },
        "source_frame": {"frame_path": "home-source.png", "frame_sha256": "a" * 64},
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
    }
    result.update(overrides)
    return result

def no_work_readiness():
    return {
        "reason": "NO_AFFORDABLE_ALLOWLISTED_OFFER",
        "weekly_inventory": {
            "complete": True, "reason": "",
            "frame_refs": ("weekly-page.png",), "frame_sha256s": ("b" * 64,),
        },
        "weekly_offers": ({
            "shop_identity": "Weekly Offers", "item_identity": "Bioenhance Scheme",
            "currency_identity": "Alliance Coins", "unit_price": 80000,
            "balance": 1000, "stock": 2, "rarity": None, "available": True,
            "premium": False, "recognized": True, "offer_identity": "weekly:bioenhance-scheme",
        },),
        "fallback_inventory": {
            "complete": True, "reason": "EXACT_FALLBACK_NOT_PRESENT",
            "frame_refs": ("other-page.png",), "frame_sha256s": ("c" * 64,),
        },
        "fallback_offer": None,
    }

def fallback_purchase_result(*, weekly_balance=1000, weekly_complete=True):
    fallback = {
        "shop_identity": "Other", "offer_identity": "Other:exact-fallback",
        "item_identity": "1★ Gear Enhance Material", "currency_identity": "Alliance Coins",
        "rarity": 1, "unit_price": 10, "balance_before": 100,
        "stock_before": 3, "item_quantity_before": 4, "quantity": 1, "total": 10,
    }
    selection_evidence = {
        "weekly_inventory": {
            "complete": weekly_complete, "reason": "",
            "frame_refs": ("weekly-page.png",), "frame_sha256s": ("b" * 64,),
        },
        "weekly_offers": ({
            "shop_identity": "Weekly Offers", "item_identity": "Bioenhance Scheme",
            "currency_identity": "Alliance Coins", "unit_price": 80000,
            "balance": weekly_balance, "stock": 2, "rarity": None, "available": True,
            "premium": False, "recognized": True, "offer_identity": "weekly:bioenhance-scheme",
        },),
        "fallback_inventory": {
            "complete": True, "reason": "",
            "frame_refs": ("other-page.png",), "frame_sha256s": ("c" * 64,),
        },
        "fallback_offer": {
            "shop_identity": "Other", "item_identity": "1★ Gear Enhance Material",
            "currency_identity": "Alliance Coins", "unit_price": 10, "balance": 100,
            "stock": 3, "rarity": 1, "available": True, "premium": False,
            "recognized": True, "offer_identity": "Other:exact-fallback",
        },
    }
    return native_result(selected_offer=fallback, selection_evidence=selection_evidence)


class AllianceShopServiceAdapterTests(unittest.TestCase):
    def test_timed_diamond_affordability_and_exact_currency_admission(self):
        from automation_service.alliance_shop import _validate_offer_evidence, _validate_unaffordable_offer
        row = {
            "shop_identity": "Weekly Offers", "item_identity": "Timed Recruit Coin",
            "currency_identity": "Diamonds", "unit_price": 1000, "balance": 1000,
            "stock": 5, "available": True, "rarity": None, "premium": True,
            "recognized": True, "offer_identity": "Weekly Offers:Timed Recruit Coin",
        }
        _validate_offer_evidence(row, shop="Weekly Offers", item="Timed Recruit Coin", rarity=None)
        with self.assertRaises(ValueError):
            _validate_unaffordable_offer(row, shop="Weekly Offers", item="Timed Recruit Coin", rarity=None)
        for balance in (999, None):
            _validate_unaffordable_offer(
                {**row, "balance": balance}, shop="Weekly Offers", item="Timed Recruit Coin", rarity=None,
            )
        with self.assertRaises(ValueError):
            _validate_offer_evidence(
                {**row, "item_identity": "Int. Recruit Coin"}, shop="Weekly Offers", item="Int. Recruit Coin", rarity=None,
            )

    def _identity(self, now=1_700_000_000.0):
        binding = resource_fixed_runtime_binding()
        backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(now, timezone.utc))
        identity = SchedulerIdentity(
            account_id=backend.account_id, server_id=backend.server_id,
            reset_id=recruitment_reset(now), task_id=ALLIANCE_SHOP_PRODUCT_ID,
        )
        return binding, identity, now

    def _runner(self, native, directory, now):
        binding, _identity, _ = self._identity(now)
        return AllianceShopRunner(
            serial=binding.serial, output_directory=Path(directory),
            native=native, utc_clock=lambda: now, monotonic_clock=lambda: 33.0,
            settle_seconds=0,
        )

    def _invoke(self, payload, identity, now, occurrence="opaque-shop-test"):
        native = FakeNativeBoundary(payload)
        with tempfile.TemporaryDirectory() as directory:
            return self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key=occurrence,
            )

    def test_real_native_policy_confirmation_reaches_adapter_without_unknown_effect_flag(self):
        _binding, identity, now = self._identity()
        for fallback in (False, True):
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as directory:
                store = SafetyStore(Path(directory) / "actions.sqlite3")
                try:
                    context = safety_store_purchase_context(directory, store)
                    context.identity = identity
                    port = ActualSafetyStoreAlliancePort(context, fallback=fallback)
                    key = canonical_purchase_action_key(
                        ALLIANCE_SHOP_FLOW_ID, ALLIANCE_SHOP_PRODUCT_ID, identity, "alliance_shop",
                    )
                    payload = AllianceShopPurchaseRoute(port, action_key=key).run().to_mapping()
                    payload.update(total_input_count=7, source_frame={
                        "frame_path": "home-source.png", "frame_sha256": "a" * 64,
                    })
                    result = self._invoke(payload, identity, now)
                    self.assertEqual(result["status"], "complete_for_reset", result)
                    self.assertFalse(result["identical_retry_denied"])
                    self.assertFalse(result["effect_reconciliation_required"])
                    self.assertEqual(result["committed_action_count"], 1)
                    self.assertEqual(store.get_action_by_key(key)["final_status"], "confirmed")
                finally:
                    store.close()

    def test_runner_preserves_native_purchase_proof_and_identity_without_runtime_scope(self):
        _binding, identity, now = self._identity()
        native = FakeNativeBoundary(native_result())
        with tempfile.TemporaryDirectory() as directory:
            runner = self._runner(native, directory, now)
            checkpoints = []
            result = runner(
                identity, "prior-game-day", lambda: checkpoints.append(True),
                runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-occurrence/value:keep-whole",
            )
        self.assertEqual(result["status"], "complete_for_reset")
        self.assertEqual(result["purchase_transport_calls"], 1)
        self.assertEqual(result["committed_action_count"], 1)
        self.assertTrue(result["accounting_verified"])
        self.assertTrue(result["native_execution_verified"])
        self.assertEqual(result["reset_id"], identity.reset_id)
        self.assertEqual(result["previous_reset_id"], "prior-game-day")
        self.assertEqual(result["occurrence_key"], "opaque-occurrence/value:keep-whole")
        expected_reset = datetime.fromtimestamp(now, timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).timestamp() + 86400
        self.assertEqual(alliance_shop_next_due(result, identity, now), expected_reset)
        request = native.request
        self.assertIsInstance(request, NativeRouteRequest)
        self.assertIs(request.identity, identity)
        self.assertEqual(request.flow_id, ALLIANCE_SHOP_FLOW_ID)
        self.assertEqual(request.product_id, ALLIANCE_SHOP_PRODUCT_ID)
        self.assertEqual(request.product_revision, ALLIANCE_SHOP_PRODUCT_REVISION)
        self.assertEqual((request.max_inputs, request.max_actions), (MAX_INPUTS, MAX_ACTIONS))
        self.assertEqual(request.occurrence_key, "opaque-occurrence/value:keep-whole")
        self.assertTrue(request.arguments["action_key"].startswith("shop-purchase"))
        request.validate_identity()
        self.assertTrue(checkpoints)

    def test_other_fallback_proves_complete_unaffordable_weekly_scan(self):
        _binding, identity, now = self._identity()
        result = self._invoke(fallback_purchase_result(), identity, now)
        expected_reset = datetime.fromtimestamp(now, timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).timestamp() + 86400
        self.assertEqual(result["status"], "complete_for_reset")
        self.assertEqual(result["selected_offer"]["shop_identity"], "Other")
        self.assertEqual(alliance_shop_next_due(result, identity, now), expected_reset)

    def test_red_shortage_weekly_allows_exact_fallback_without_owned_or_balance(self):
        _binding, identity, now = self._identity()
        payload = fallback_purchase_result(weekly_balance=None)
        weekly = payload["selection_evidence"]["weekly_offers"][0]
        weekly.update(unit_price=None, stock=None, available=None, price_shortage=True)
        payload["selected_offer"]["item_quantity_before"] = None
        result = self._invoke(payload, identity, now)
        self.assertEqual(result["status"], "complete_for_reset", result)
        self.assertEqual(result["selected_offer"]["shop_identity"], "Other")
        self.assertGreater(alliance_shop_next_due(result, identity, now), now)

    def test_other_fallback_rejects_affordable_or_incomplete_weekly_scan(self):
        _binding, identity, now = self._identity()
        for payload in (
            fallback_purchase_result(weekly_balance=100000),
            fallback_purchase_result(weekly_complete=False),
        ):
            with self.subTest(weekly_balance=payload["selection_evidence"]["weekly_offers"][0]["balance"],
                              weekly_complete=payload["selection_evidence"]["weekly_inventory"]["complete"]):
                result = self._invoke(payload, identity, now)
                with self.assertRaises(ValueError):
                    alliance_shop_next_due(result, identity, now)
    def test_effect_unknown_after_one_dispatch_is_never_schedulable(self):
        _binding, identity, now = self._identity()
        payload = native_result(
            status="unresolved", purchase_transport_calls=1, committed_action_count=0,
            terminal_home_verified=False, offer_effect_verified=False,
            effect_reconciliation_required=True, identical_retry_denied=True,
        )
        native = FakeNativeBoundary(payload, failure="paired effect not proven", count=5)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-unknown",
            )
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["purchase_transport_calls"], 1)
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        with self.assertRaises(ValueError):
            alliance_shop_next_due(result, identity, now)

    def test_no_affordable_offer_uses_only_the_explicit_safe_recheck(self):
        _binding, identity, now = self._identity()
        payload = native_result(
            status="deferred", reason="NO_AFFORDABLE_ALLOWLISTED_OFFER",
            purchase_transport_calls=0, committed_action_count=0,
            selected_offer=None, offer_effect_verified=False,
            no_work_evidence=no_work_readiness(),
        )
        native = FakeNativeBoundary(payload)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-no-work",
            )
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(alliance_shop_next_due(result, identity, now), now + 300)

    def test_restart_confirmed_purchase_keeps_reset_completion_without_rebuy(self):
        _binding, identity, now = self._identity()
        payload = native_result(
            status="already_complete", purchase_transport_calls=0,
            committed_action_count=0, prior_confirmed_action_count=1,
            selected_offer=None, offer_effect_verified=False,
        )
        native = FakeNativeBoundary(payload)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-restart",
            )
        self.assertEqual(result["status"], "complete_for_reset")
        self.assertEqual(result["prior_confirmed_action_count"], 1)
        self.assertEqual(result["purchase_transport_calls"], 0)
        self.assertEqual(alliance_shop_next_due(result, identity, now),
                         datetime.fromtimestamp(now, timezone.utc).replace(
                             hour=0, minute=0, second=0, microsecond=0,
                         ).timestamp() + 86400)

    def test_incomplete_source_evidence_rejects_no_work_due(self):
        _binding, identity, now = self._identity()
        payload = native_result(
            status="deferred", reason="NO_AFFORDABLE_ALLOWLISTED_OFFER",
            purchase_transport_calls=0, committed_action_count=0,
            selected_offer=None, offer_effect_verified=False,
            no_work_evidence=no_work_readiness(), source_frame=None,
        )
        native = FakeNativeBoundary(payload)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-incomplete",
            )
        with self.assertRaises(ValueError):
            alliance_shop_next_due(result, identity, now)

    def test_missing_no_work_readiness_rejects_deferred_schedule(self):
        _binding, identity, now = self._identity()
        payload = native_result(
            status="deferred", reason="NO_AFFORDABLE_ALLOWLISTED_OFFER",
            purchase_transport_calls=0, committed_action_count=0,
            selected_offer=None, offer_effect_verified=False, no_work_evidence=None,
        )
        native = FakeNativeBoundary(payload)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-no-readiness",
            )
        with self.assertRaises(ValueError):
            alliance_shop_next_due(result, identity, now)


    def test_preflight_and_missing_native_return_blocked_mappings(self):
        binding, identity, now = self._identity()
        stale = SchedulerIdentity(identity.account_id, identity.server_id, "game-day-2023-11-13", identity.task_id)
        native = FakeNativeBoundary(native_result())
        with tempfile.TemporaryDirectory() as directory:
            stale_result = self._runner(native, directory, now)(
                stale, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-stale",
            )
        self.assertEqual(stale_result["status"], "blocked")
        self.assertIsNone(native.request)
        with tempfile.TemporaryDirectory() as directory:
            wrong_runtime = AllianceShopRunner(
                serial="different-emulator", output_directory=Path(directory),
                native=native, utc_clock=lambda: now,
            )
            wrong_result = wrong_runtime(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-wrong-runtime",
            )
        self.assertEqual(wrong_result["status"], "blocked")
        self.assertIsNone(native.request)
        with tempfile.TemporaryDirectory() as directory:
            missing = AllianceShopRunner(output_directory=Path(directory), native=None, utc_clock=lambda: now)
            result = missing(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-unbound",
            )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["purchase_transport_calls"], 0)


if __name__ == "__main__":
    unittest.main()
