from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from safe_action_core import (
    CentralPolicy,
    Observation,
    PolicyDecision,
    PolicyRequest,
    PromotionalBackSequence,
    PromotionalSequenceError,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
)
from safe_action_core.promotional import (
    MAX_PROMOTIONAL_BACKS,
    PROMOTIONAL_BACK_GEOMETRY,
    PROMOTIONAL_BACK_TARGET_ROI,
    PROMOTIONAL_STATE,
    SAFE_PROMOTIONAL_BACK,
)
from scripts.promotional_escape import classify_promotional_back
from scripts.startup_normalization import load_frame


ROOT = Path(__file__).resolve().parents[1]
PROFILE_ID = json.loads((ROOT / "runtime-profile/manifest.json").read_text(encoding="utf-8"))["profile_id"]
NAVIGATION_ASSETS = ROOT / "tasks/assets/navigation/800x1280"
PROMO_FRAME = NAVIGATION_ASSETS / "reset_reconcile.png"
ARROW_REFERENCE = NAVIGATION_ASSETS / "cash_mall_startup.png"


def promo_observation(**changes):
    base = Observation(
        frame_sha256="a" * 64,
        capture_completed_monotonic=999.5,
        runtime_profile_id=PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state=PROMOTIONAL_STATE,
        overlay_state="promotional_unknown_nonintersecting",
        target_identity="standard-game-back-arrow",
        target_roi=PROMOTIONAL_BACK_TARGET_ROI,
        recognized=True,
        control_class=SAFE_PROMOTIONAL_BACK,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition="HOME_BASE",
        critical_roi_hashes=(("arrow_target", "b" * 64),),
        source_family="promotional",
        target_isolated=True,
        forbidden_region_intersects_target=False,
        arrow_geometry=PROMOTIONAL_BACK_GEOMETRY,
        forbidden_regions=(("purchase", (40, 950, 760, 1260)),),
    )
    return replace(base, **changes)


def promo_request(obs=None, **changes):
    base = PolicyRequest(
        action_id="promo-1",
        action_key="startup:promo-back:1",
        task_id="MVP-QUEST-TO-CLAIM",
        task_mode="supervised_validation",
        semantic_action=SAFE_PROMOTIONAL_BACK,
        expected_runtime_profile_id=PROFILE_ID,
        observation=obs or promo_observation(),
        monotonic_now=1000.0,
        observation_max_age_seconds=3.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="promo-owner",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        promotional_back_count=0,
    )
    return replace(base, **changes)


class PromotionalClassifierTests(unittest.TestCase):
    def setUp(self):
        self.frame = load_frame(PROMO_FRAME)
        self.reference = load_frame(ARROW_REFERENCE)

    def test_retained_top_up_page_is_escape_only(self):
        decision = classify_promotional_back(self.frame, self.reference)
        self.assertTrue(decision.recognized)
        self.assertEqual(decision.state, PROMOTIONAL_STATE)
        self.assertEqual(decision.control_class, SAFE_PROMOTIONAL_BACK)
        self.assertTrue(decision.target_isolated)
        self.assertGreaterEqual(decision.arrow_similarity, 0.82)

    def test_artwork_change_outside_critical_arrow_roi_is_allowed(self):
        changed = self.frame.copy()
        changed[700:750, 300:350] = 0
        decision = classify_promotional_back(changed, self.reference)
        self.assertTrue(decision.recognized)

    def test_forbidden_region_overlap_denies_isolation(self):
        decision = classify_promotional_back(
            self.frame,
            self.reference,
            forbidden_regions=(("purchase", (40, 0, 760, 100)),),
        )
        self.assertFalse(decision.recognized)
        self.assertIn("FORBIDDEN_REGION_INTERSECTS_TARGET", decision.denial_rules)

    def test_missing_or_moved_arrow_denies(self):
        blanked = self.frame.copy()
        blanked[5:60, 45:130] = 0
        self.assertFalse(classify_promotional_back(blanked, self.reference).recognized)
        moved = self.frame.copy()
        moved[5:60, 45:130] = 0
        moved[40:95, 180:265] = self.reference[5:60, 45:130]
        self.assertFalse(classify_promotional_back(moved, self.reference).recognized)


class PromotionalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = CentralPolicy()

    def test_exact_escape_authorizes_and_is_only_navigation_action(self):
        result = self.policy.evaluate(promo_request())
        self.assertEqual(result.decision, PolicyDecision.AUTHORIZE)
        self.assertEqual(result.reason_code, "AUTHORIZED_SAFE_PROMOTIONAL_BACK")

    def test_escape_requires_semantic_arrow_and_geometry(self):
        for changes in (
            {"target_identity": "coordinate-only"},
            {"arrow_geometry": "generic-arrow"},
            {"target_isolated": False},
            {"forbidden_region_intersects_target": True},
            {"control_class": "PURCHASE"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.policy.evaluate(promo_request(promo_observation(**changes))).decision, PolicyDecision.DENY)

    def test_escape_denies_hard_stops_and_non_navigation_costs(self):
        for changes in (
            {"os_surface": True},
            {"hard_stop_detected": True},
            {"package_foreground": False},
            {"cost_type": "real_money", "cost_amount": 1},
            {"consequence": "purchase"},
            {"expected_postcondition": "PAYMENT_DIALOG"},
        ):
            with self.subTest(changes=changes):
                result = self.policy.evaluate(promo_request(promo_observation(**changes)))
                self.assertNotEqual(result.decision, PolicyDecision.AUTHORIZE)

    def test_fourth_escape_is_denied(self):
        result = self.policy.evaluate(promo_request(promotional_back_count=MAX_PROMOTIONAL_BACKS))
        self.assertEqual(result.reason_code, "PROMOTIONAL_BACK_LIMIT")

    def test_unresolved_and_missing_lease_still_block_escape(self):
        self.assertEqual(self.policy.evaluate(promo_request(unresolved_action=True)).decision, PolicyDecision.GLOBAL_INPUT_LOCK)
        self.assertEqual(self.policy.evaluate(promo_request(lease_valid=False)).reason_code, "LEASE_REQUIRED")


class PromotionalSequenceTests(unittest.TestCase):
    def test_three_independent_actions_then_limit(self):
        sequence = PromotionalBackSequence()
        self.assertTrue(sequence.can_attempt())
        self.assertEqual(sequence.record_confirmed(PROMOTIONAL_STATE), "promotional_continuation")
        self.assertEqual(sequence.record_confirmed(PROMOTIONAL_STATE), "promotional_continuation")
        self.assertEqual(sequence.record_confirmed("CASH_MALL"), "known_safe_state")
        self.assertFalse(sequence.can_attempt())
        with self.assertRaises(PromotionalSequenceError):
            sequence.record_confirmed(PROMOTIONAL_STATE)

    def test_unknown_successor_stops_sequence(self):
        with self.assertRaises(PromotionalSequenceError):
            PromotionalBackSequence().record_confirmed("UNKNOWN")


class PromotionalExecutorTests(unittest.TestCase):
    def test_known_successor_confirms_with_one_transport_call(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SafetyStore(Path(temp) / "actions.sqlite3")
            store.acquire_lease("promo-owner", 1000.0, 30.0)
            clock = [1000.0]
            calls = []
            immediate = promo_observation(frame_sha256="c" * 64, capture_completed_monotonic=1000.1)
            successor = promo_observation(
                frame_sha256="d" * 64,
                capture_completed_monotonic=1000.2,
                source_state="HOME_BASE",
                overlay_state="none_observed",
                target_identity=None,
                target_roi=None,
                source_family=None,
                target_isolated=False,
                arrow_geometry=None,
                recognized=True,
            )
            executor = SafeActionExecutor(
                store,
                CentralPolicy(),
                "promo-owner",
                lambda: clock[0],
                lambda intent: (calls.append(intent.action_id) or TransportResult(True, "DISPATCHED")),
                lambda: (clock.__setitem__(0, 1000.2) or immediate),
                lambda: [successor],
                lambda _intent, obs: obs.source_state == "HOME_BASE",
            )
            result = executor.execute(promo_request())
            self.assertEqual(result.status.value, "confirmed")
            self.assertEqual(result.transport_calls, 1)
            self.assertEqual(calls, ["promo-1"])
            self.assertEqual(store.get_action("promo-1")["final_status"], "confirmed")
            store.close()

    def test_changed_arrow_before_dispatch_cancels_without_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SafetyStore(Path(temp) / "actions.sqlite3")
            store.acquire_lease("promo-owner", 1000.0, 30.0)
            calls = []
            changed = promo_observation(frame_sha256="c" * 64, capture_completed_monotonic=1000.1, arrow_geometry="changed")
            executor = SafeActionExecutor(
                store,
                CentralPolicy(),
                "promo-owner",
                lambda: 1000.0,
                lambda intent: (calls.append(intent.action_id) or TransportResult(True, "DISPATCHED")),
                lambda: changed,
                lambda: [],
                lambda _intent, _obs: False,
            )
            result = executor.execute(promo_request())
            self.assertEqual(result.status.value, "cancelled")
            self.assertEqual(result.transport_calls, 0)
            self.assertEqual(calls, [])
            self.assertEqual(store.get_action("promo-1")["final_status"], "cancelled")
            store.close()


if __name__ == "__main__":
    unittest.main()
