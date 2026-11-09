from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from automation_service.daily_shops import DailyShopsRunner, MAX_ACTIONS, MAX_INPUTS, daily_shops_next_due
from automation_service.native_execution import NativeRouteOutcome, NativeRouteRequest
from automation_service.registry import (
    DAILY_SHOPS_FLOW_ID,
    DAILY_SHOPS_PRODUCT_ID,
    DAILY_SHOPS_PRODUCT_REVISION,
)
from automation_service.recruitment import recruitment_reset
from tasks.purchases_disabled import canonical_purchase_action_key
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity
from safe_action_core import SafetyStore
from scripts.daily_shops_bluestacks import DailyShopsPurchaseRoute
from tests.test_daily_shops_bluestacks import (
    ActualSafetyStorePairedShopPort, safety_store_purchase_context,
)

class FakeRuntimeInputLock:
    owner = "automation-service"
    invocation_id = "daily-shops-service-invocation"
    held = True

    def assert_held(self, owner, invocation_id):
        if (owner, invocation_id) != (self.owner, self.invocation_id):
            raise AssertionError("daily shops runtime owner changed")


class FakeNativeBoundary:
    flow_id = DAILY_SHOPS_FLOW_ID
    product_id = DAILY_SHOPS_PRODUCT_ID
    product_revision = DAILY_SHOPS_PRODUCT_REVISION
    from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID as runtime_profile_id
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, result, *, failure=None, count=9, accounting=True):
        self.result, self.failure, self.count, self.accounting = result, failure, count, accounting
        self.request = None

    def run(self, request: NativeRouteRequest):
        self.request = request
        return NativeRouteOutcome(
            flow_id=DAILY_SHOPS_FLOW_ID,
            native_result=self.result,
            partial_result=None,
            failure=self.failure,
            invocation_id=FakeRuntimeInputLock.invocation_id,
            session_directory="/synthetic/daily-shops",
            startup_recovery=None,
            input_count=self.count,
            session_input_count=self.count,
            runtime_input_count=self.count,
            accounting_verified=self.accounting,
        )


def route_result(identity, **overrides):
    action_keys = {
        "ruins": canonical_purchase_action_key(
            DAILY_SHOPS_FLOW_ID, DAILY_SHOPS_PRODUCT_ID, identity, "ruins_shop",
        ),
        "rare_earth": canonical_purchase_action_key(
            DAILY_SHOPS_FLOW_ID, DAILY_SHOPS_PRODUCT_ID, identity, "rare_earth_shop",
        ),
    }
    result = {
        "status": "completed",
        "purchase_transport_calls": 2,
        "committed_action_count": 2,
        "accounting_verified": True,
        "total_input_count": 9,
        "terminal_home_verified": True,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "source_frame": {"frame_path": "/synthetic/home.png", "frame_sha256": "a" * 64},
        "tab_results": {
            "ruins": {
                "status": "confirmed", "effect_verified": True, "action_key": action_keys["ruins"],
                "reason": "TAB_ITEM_CURRENCY_AND_SUCCESSOR_CONFIRMED", "quantity": 100,
                "total": 1500, "offer_identity": "ruins:chip", "shop_identity": "Ruins Shop",
                "item_identity": "3★ Chip Enhance Material", "currency_identity": "Ruins Coins",
                "rarity": 3, "unit_price": 15, "balance_before": 16649, "stock_before": 100,
                "item_quantity_before": 4, "source_frame_ref": "ruins-offer.png",
                "source_frame_sha256": "b" * 64,
            },
            "rare_earth": {
                "status": "confirmed", "effect_verified": True, "action_key": action_keys["rare_earth"],
                "reason": "TAB_ITEM_CURRENCY_AND_SUCCESSOR_CONFIRMED", "quantity": 15,
                "total": 207000, "offer_identity": "rare-earth:module", "shop_identity": "Rare Earth Shop",
                "item_identity": "3★ Module Enhance Material", "currency_identity": "Rare Earth",
                "rarity": 3, "unit_price": 13800, "balance_before": 211995, "stock_before": 20,
                "item_quantity_before": 4, "source_frame_ref": "rare-earth-offer.png",
                "source_frame_sha256": "c" * 64,
            },
        },
    }
    result.update(overrides)
    return result


class DailyShopsServiceAdapterTests(unittest.TestCase):
    def _identity(self, now=1_700_000_000.0):
        binding = resource_fixed_runtime_binding()
        backend = derive_resource_runtime_identity(binding, datetime.fromtimestamp(now, timezone.utc))
        return binding, SchedulerIdentity(
            account_id=backend.account_id, server_id=backend.server_id,
            reset_id=recruitment_reset(now), task_id=DAILY_SHOPS_PRODUCT_ID,
        ), now

    def _runner(self, native, directory, now):
        binding, _identity, _ = self._identity(now)
        return DailyShopsRunner(
            serial=binding.serial, output_directory=Path(directory),
            native=native, utc_clock=lambda: now, monotonic_clock=lambda: 33.0,
            settle_seconds=0,
        )

    def test_real_native_confirmations_reach_adapter_and_partial_due_without_unknown_projection(self):
        _binding, identity, now = self._identity()
        keys = {tab: canonical_purchase_action_key(
            DAILY_SHOPS_FLOW_ID, DAILY_SHOPS_PRODUCT_ID, identity,
            "ruins_shop" if tab == "ruins" else "rare_earth_shop",
        ) for tab in ("ruins", "rare_earth")}
        for partial, unproved in ((False, False), (True, False), (False, True)):
            with self.subTest(unaffordable_second=partial, unproved_first=unproved), tempfile.TemporaryDirectory() as directory:
                store = SafetyStore(Path(directory) / "actions.sqlite3")
                try:
                    context = safety_store_purchase_context(directory, store)
                    context.identity = identity
                    port = ActualSafetyStorePairedShopPort(
                        context, unaffordable_second=partial, unproved_first=unproved,
                    )
                    context.monotonic_clock = lambda: float(port.capture_count) + 0.1
                    payload = DailyShopsPurchaseRoute(port, action_keys=keys).run().to_mapping()
                    payload.update(total_input_count=9, source_frame={
                        "frame_path": "home-source.png", "frame_sha256": "a" * 64,
                    })
                    result = self._runner(FakeNativeBoundary(payload), directory, now)(
                        identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                        occurrence_key="native-policy-partial" if partial or unproved else "native-policy-complete",
                    )
                    self.assertEqual(result["status"], "deferred" if partial or unproved else "complete_for_reset", result)
                    self.assertFalse(result["identical_retry_denied"])
                    self.assertFalse(result["effect_reconciliation_required"])
                    self.assertEqual(result["committed_action_count"], 1 if partial or unproved else 2)
                    self.assertEqual(port.home_calls, 1)
                    if partial or unproved:
                        self.assertEqual(daily_shops_next_due(result, identity, now), now + 300)
                finally:
                    store.close()

    def test_runner_preserves_fixed_native_request_and_full_reset_completion(self):
        _binding, identity, now = self._identity()
        native = FakeNativeBoundary(route_result(identity))
        with tempfile.TemporaryDirectory() as directory:
            runner = self._runner(native, directory, now)
            checkpoints = []
            result = runner(
                identity, "prior-game-day", lambda: checkpoints.append(True),
                runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-occurrence/value:keep-whole",
            )
        self.assertEqual(result["status"], "complete_for_reset")
        self.assertEqual(result["purchase_transport_calls"], 2)
        self.assertEqual(result["committed_action_count"], 2)
        self.assertTrue(result["accounting_verified"])
        self.assertTrue(result["native_execution_verified"])
        expected_reset = datetime.fromtimestamp(now, timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).timestamp() + 86400
        self.assertEqual(daily_shops_next_due(result, identity, now), expected_reset)
        request = native.request
        self.assertIsInstance(request, NativeRouteRequest)
        self.assertIs(request.identity, identity)
        self.assertEqual(request.flow_id, DAILY_SHOPS_FLOW_ID)
        self.assertEqual(request.product_id, DAILY_SHOPS_PRODUCT_ID)
        self.assertEqual(request.product_revision, DAILY_SHOPS_PRODUCT_REVISION)
        self.assertEqual((request.max_inputs, request.max_actions), (MAX_INPUTS, MAX_ACTIONS))
        self.assertEqual(request.occurrence_key, "opaque-occurrence/value:keep-whole")
        self.assertEqual(set(request.arguments["action_keys"]), {"ruins", "rare_earth"})
        self.assertNotEqual(request.arguments["action_keys"]["ruins"], request.arguments["action_keys"]["rare_earth"])
        request.validate_identity()
        self.assertTrue(checkpoints)

    def test_fresh_confirmed_tab_and_no_work_tab_are_partial_and_recheck_safely(self):
        _binding, identity, now = self._identity()
        base = route_result(identity)
        rows = {tab: dict(row) for tab, row in base["tab_results"].items()}
        rows["rare_earth"].update(
            status="deferred", effect_verified=False, reason="TAB_INSUFFICIENT_CURRENCY",
            quantity=0, total=None, balance_before=0,
        )
        payload = route_result(
            identity, status="deferred", purchase_transport_calls=1, committed_action_count=1,
            total_input_count=6, tab_results=rows,
        )
        native = FakeNativeBoundary(payload, count=6)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-partial-fresh",
            )
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["committed_action_count"], 1)
        self.assertEqual(result["purchase_transport_calls"], 1)
        self.assertEqual(result["tab_results"]["ruins"]["quantity"], 100)
        self.assertEqual(result["tab_results"]["rare_earth"]["quantity"], 0)
        self.assertEqual(daily_shops_next_due(result, identity, now), now + 300)

    def test_committed_tab_with_zero_quantity_blocked_sibling_defers_safely(self):
        _binding, identity, now = self._identity()
        base = route_result(identity)
        rows = {tab: dict(row) for tab, row in base["tab_results"].items()}
        rows["rare_earth"].update(
            status="blocked", effect_verified=False, reason="TAB_OFFER_NOT_RECOGNIZED",
            quantity=0, total=None, balance_before=0,
        )
        payload = route_result(
            identity, status="deferred", purchase_transport_calls=1, committed_action_count=1,
            total_input_count=5, tab_results=rows,
        )
        native = FakeNativeBoundary(payload, count=5)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-partial-blocked",
            )
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["committed_action_count"], 1)
        self.assertEqual(result["purchase_transport_calls"], 1)
        self.assertEqual(daily_shops_next_due(result, identity, now), now + 300)

    def test_restart_confirmed_tab_counts_once_without_rebuy_or_transport(self):
        _binding, identity, now = self._identity()
        base = route_result(identity)
        rows = {tab: dict(row) for tab, row in base["tab_results"].items()}
        rows["ruins"].update(status="already_confirmed", reason="TAB_OCCURRENCE_ALREADY_CONFIRMED")
        rows["rare_earth"].update(
            status="deferred", effect_verified=False, reason="TAB_INSUFFICIENT_CURRENCY",
            quantity=0, total=None, balance_before=0,
        )
        payload = route_result(
            identity, status="deferred", purchase_transport_calls=0, committed_action_count=0,
            total_input_count=4, tab_results=rows,
        )
        native = FakeNativeBoundary(payload, count=4)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-partial-restart",
            )
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["committed_action_count"], 0)
        self.assertEqual(result["purchase_transport_calls"], 0)
        self.assertEqual(result["tab_results"]["ruins"]["status"], "already_confirmed")
        self.assertEqual(daily_shops_next_due(result, identity, now), now + 300)

    def test_no_work_requires_exact_per_tab_readiness_and_recheck(self):
        _binding, identity, now = self._identity()
        base = route_result(identity)
        rows = {tab: dict(row) for tab, row in base["tab_results"].items()}
        for row in rows.values():
            row.update(
                status="deferred", effect_verified=False, reason="TAB_INSUFFICIENT_CURRENCY",
                quantity=0, total=None, balance_before=0,
            )
        rows["ruins"].update(
            reason="TAB_STOCK_EXHAUSTED", stock_before=0, item_quantity_before=None,
        )
        payload = route_result(
            identity, status="deferred", purchase_transport_calls=0, committed_action_count=0,
            tab_results=rows,
        )
        native = FakeNativeBoundary(payload)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-no-work",
            )
        self.assertEqual(daily_shops_next_due(result, identity, now), now + 300)
        payload["tab_results"]["rare_earth"]["reason"] = "UNKNOWN_READINESS"
        native = FakeNativeBoundary(payload)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-bad-readiness",
            )
        with self.assertRaises(ValueError):
            daily_shops_next_due(result, identity, now)

    def test_restart_confirmed_tab_with_blocked_sibling_defers_without_rebuy(self):
        _binding, identity, now = self._identity()
        rows = {tab: dict(row) for tab, row in route_result(identity)["tab_results"].items()}
        rows["ruins"].update(status="already_confirmed")
        rows["rare_earth"].update(
            status="blocked", effect_verified=False, quantity=0, total=None,
            reason="EXACT_TAB_OFFER_NOT_AVAILABLE",
        )
        payload = route_result(
            identity, status="deferred", purchase_transport_calls=0, committed_action_count=0,
            tab_results=rows,
        )
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(FakeNativeBoundary(payload), directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-restart-blocked-tab",
            )
        self.assertEqual(result["status"], "deferred", result)
        self.assertEqual(result["committed_action_count"], 0)
        self.assertEqual(result["purchase_transport_calls"], 0)
        self.assertEqual(daily_shops_next_due(result, identity, now), now + 300)

    def test_blocked_sibling_with_nonzero_quantity_is_not_safe_partial(self):
        _binding, identity, now = self._identity()
        rows = {tab: dict(row) for tab, row in route_result(identity)["tab_results"].items()}
        rows["rare_earth"].update(status="blocked", effect_verified=False,
                                 reason="EXACT_TAB_OFFER_NOT_AVAILABLE")
        payload = route_result(
            identity, status="deferred", purchase_transport_calls=1, committed_action_count=1,
            tab_results=rows,
        )
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(FakeNativeBoundary(payload), directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-invalid-blocked-quantity",
            )
        with self.assertRaises(ValueError):
            daily_shops_next_due(result, identity, now)

    def test_dispatched_unknown_purchase_is_unresolved_and_unschedulable(self):
        _binding, identity, now = self._identity()
        base = route_result(identity)
        keys = {tab: row["action_key"] for tab, row in base["tab_results"].items()}
        payload = route_result(
            identity, status="unresolved", purchase_transport_calls=1, committed_action_count=0,
            effect_reconciliation_required=True, identical_retry_denied=True,
            tab_results={
                "ruins": {"status": "unresolved", "effect_verified": False, "action_key": keys["ruins"]},
                "rare_earth": {"status": "blocked", "effect_verified": False, "action_key": keys["rare_earth"]},
            },
        )
        native = FakeNativeBoundary(payload, failure="effect unknown", count=5)
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-unknown-effect",
            )
        self.assertEqual(result["status"], "unresolved")
        self.assertTrue(result["effect_reconciliation_required"])
        self.assertTrue(result["identical_retry_denied"])
        self.assertEqual(result["purchase_transport_calls"], 1)
        with self.assertRaises(ValueError):
            daily_shops_next_due(result, identity, now)

    def test_reset_and_backend_mismatch_return_blocked_mappings_before_dispatch(self):
        binding, identity, now = self._identity()
        stale = SchedulerIdentity(identity.account_id, identity.server_id, "game-day-2023-11-13", identity.task_id)
        native = FakeNativeBoundary(route_result(identity))
        with tempfile.TemporaryDirectory() as directory:
            result = self._runner(native, directory, now)(
                stale, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-stale",
            )
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(native.request)
        with tempfile.TemporaryDirectory() as directory:
            runner = DailyShopsRunner(
                serial="different-emulator", output_directory=Path(directory),
                native=native, utc_clock=lambda: now,
            )
            result = runner(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-wrong-backend",
            )
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(native.request)

    def test_missing_native_binding_blocks_without_dispatch(self):
        _binding, identity, now = self._identity()
        with tempfile.TemporaryDirectory() as directory:
            runner = DailyShopsRunner(output_directory=Path(directory), native=None, utc_clock=lambda: now)
            result = runner(
                identity, None, lambda: None, runtime_input_lock=FakeRuntimeInputLock(),
                occurrence_key="opaque-unbound",
            )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["purchase_transport_calls"], 0)
        self.assertFalse(result["accounting_verified"])


if __name__ == "__main__":
    unittest.main()
