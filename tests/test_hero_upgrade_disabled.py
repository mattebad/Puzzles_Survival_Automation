from __future__ import annotations

from dataclasses import replace
import unittest

from tasks.hero_upgrade_disabled import (
    ANTISERUM,
    EVOLUTION_SCREEN,
    EVOLUTION_TARGET,
    HERO_SCREEN,
    HERO_TARGET,
    PRODUCT_ID,
    PRODUCT_REVISION,
    STANDARD_MANUALS,
    HeroUpgradeObservation,
    hero_evolution_authorizeable,
    hero_evolution_postcondition_verified,
    hero_evolution_spec,
    hero_upgrade_authorizeable,
    hero_upgrade_postcondition_verified,
    hero_upgrade_spec,
)
from tasks.profile import BLUESTACKS_NATIVE_TARGET_PROVENANCE


ROI = (10, 10, 20, 20)
PANEL = (0, 0, 100, 100)
SOURCE_HASH = "a" * 64


def observation(**changes) -> HeroUpgradeObservation:
    values = dict(
        screen_state=HERO_SCREEN,
        hero_identity="Wali",
        hero_selected=True,
        current_level=9,
        evolution_cap=10,
        material_costs={ANTISERUM: 200},
        material_balances={ANTISERUM: 1_000},
        target_identity=HERO_TARGET,
        target_roi=ROI,
        panel_bounds=PANEL,
        control_class="UPGRADE",
        game_day_id="reset-17",
        confirmed_upgrades=0,
        material_rows_complete=True,
        stable_selected_state=True,
        normal_upgrade_visible=True,
        normal_single_upgrade=True,
        evolution_control_visible=False,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=SOURCE_HASH,
        evidence_refs=("synthetic:wali-panel",),
    )
    values.update(changes)
    return HeroUpgradeObservation(**values)


def evolution_observation(**changes) -> HeroUpgradeObservation:
    values = dict(
        screen_state=EVOLUTION_SCREEN,
        current_level=10,
        evolution_cap=10,
        next_evolution_cap=20,
        material_costs={ANTISERUM: 200, "COMBAT_MANUAL_I": 30},
        material_balances={ANTISERUM: 1_000, "COMBAT_MANUAL_I": 50},
        target_identity=EVOLUTION_TARGET,
        control_class="EVOLVE",
        normal_upgrade_visible=False,
        normal_single_upgrade=False,
        evolution_control_visible=True,
    )
    values.update(changes)
    return observation(**values)


def settled(
    before: HeroUpgradeObservation,
    *,
    current_level: int | None = None,
    evolution_cap: int | None = None,
    confirmed_upgrades: int | None = None,
    material_balances: dict[str, int] | None = None,
    spent_materials: dict[str, int] | None = None,
    material_usage_receipts: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = ("synthetic:wali-settled",),
) -> HeroUpgradeObservation:
    return replace(
        before,
        screen_state=HERO_SCREEN,
        current_level=current_level if current_level is not None else before.current_level + 1,
        evolution_cap=evolution_cap if evolution_cap is not None else before.evolution_cap,
        confirmed_upgrades=(
            confirmed_upgrades
            if confirmed_upgrades is not None
            else before.confirmed_upgrades + 1
        ),
        target_identity=HERO_TARGET,
        control_class="UPGRADE",
        material_balances=(material_balances if material_balances is not None else dict(before.material_balances)),
        spent_materials=spent_materials if spent_materials is not None else {},
        material_usage_receipts=material_usage_receipts,
        evidence_refs=evidence_refs,
    )


class WaliUpgradeContractTests(unittest.TestCase):
    def test_normal_upgrade_requires_selected_wali_exact_standard_single_and_current_evidence(self):
        before = observation()
        self.assertTrue(hero_upgrade_authorizeable(before))
        for changes in (
            {"hero_identity": "Another Hero"},
            {"hero_selected": False},
            {"stable_selected_state": False},
            {"current_level": 10},
            {"control_class": "UPGRADE_TO_LEVEL"},
            {"normal_single_upgrade": False},
            {"material_costs": {ANTISERUM: 200, "COMBAT_MANUAL_I": 1}},
            {"material_rows_complete": False},
            {"material_balances": {ANTISERUM: 199}},
            {"target_identity": "bulk-upgrade"},
            {"game_day_id": ""},
            {"confirmed_upgrades": 3},
            {"reset_guard_active": True},
            {"target_provenance": "unknown"},
            {"source_frame_sha256": "bad"},
            {"evidence_refs": ()},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(hero_upgrade_authorizeable(replace(before, **changes)))

    def test_normal_spec_is_one_actual_cost_antiserum_action_with_ordered_reset_fence(self):
        before = observation(confirmed_upgrades=2, current_level=29, evolution_cap=30)
        spec = hero_upgrade_spec(before)
        self.assertEqual(spec.action_kind, "HERO_UPGRADE_SINGLE")
        self.assertEqual(spec.expected_source_screen, HERO_SCREEN)
        self.assertEqual(spec.subject, "Wali")
        self.assertEqual(spec.quantity, 1)
        self.assertEqual(spec.resource_or_currency, ANTISERUM)
        self.assertEqual(spec.maximum_cost, 200)
        self.assertFalse(spec.free_only)
        self.assertEqual(spec.allowed_confirmation_dialogs, ())
        self.assertEqual(
            spec.semantic_preconditions,
            (
                f"product_id={PRODUCT_ID}",
                f"product_revision={PRODUCT_REVISION}",
                "reset_identity=reset-17",
                "confirmed_upgrades=2",
                "next_upgrade_ordinal=3",
                "hero_identity=Wali",
                "hero_selected=true",
                "current_level=29",
                "evolution_cap=30",
                "target_identity=hero-upgrade",
                "control_class=UPGRADE",
                "normal_single_upgrade=true",
                "bulk_upgrade=false",
                "standard_materials_only=true",
                "material_cost.ANTISERUM=200",
                "material_balance.ANTISERUM=1000",
                "stable_selected_state=true",
                "native_target_evidence=true",
                "reset_action=false",
            ),
        )
        self.assertEqual(
            spec.semantic_postconditions,
            (
                "hero_identity=Wali",
                "same_reset_identity=true",
                "current_level=before+1",
                "confirmed_upgrades=before+1",
                "exact_ANTISERUM_debit=true",
                "normal_level_delta_only=true",
                "reset_action=false",
            ),
        )

    def test_normal_successor_requires_exact_level_count_reset_and_antiserum_debit(self):
        before = observation(confirmed_upgrades=2)
        after = settled(
            before,
            material_balances={ANTISERUM: 800},
            spent_materials={ANTISERUM: 200},
        )
        # A next-level cost can be higher than the remaining balance; this action is still verified.
        after = replace(after, material_costs={ANTISERUM: 900})
        self.assertTrue(hero_upgrade_postcondition_verified(before, after))
        self.assertTrue(
            hero_upgrade_postcondition_verified(
                before,
                replace(
                    after,
                    current_level=10,
                    target_identity=EVOLUTION_TARGET,
                    control_class="EVOLVE",
                    normal_upgrade_visible=False,
                    normal_single_upgrade=False,
                    evolution_control_visible=True,
                ),
            )
        )
        for changes in (
            {"current_level": 11},
            {"evolution_cap": 11},
            {"confirmed_upgrades": 2},
            {"game_day_id": "reset-18"},
            {"material_balances": {ANTISERUM: 801}},
            {"spent_materials": {ANTISERUM: 199}},
            {"stable_selected_state": False},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(hero_upgrade_postcondition_verified(before, replace(after, **changes)))
        self.assertFalse(
            hero_upgrade_postcondition_verified(
                before,
                replace(after, material_balances={}, spent_materials={}),
            )
        )

    def test_evolution_requires_displayed_cap_next_cap_and_complete_affordable_standard_vector(self):
        before = evolution_observation(confirmed_upgrades=2)
        self.assertTrue(hero_evolution_authorizeable(before))
        for changes in (
            {"current_level": 9},
            {"next_evolution_cap": None},
            {"next_evolution_cap": 10},
            {"evolution_control_visible": False},
            {"control_class": "UPGRADE"},
            {"target_identity": "hero-upgrade"},
            {"material_costs": {ANTISERUM: 200}},
            {"material_costs": {ANTISERUM: 200, "PREMIUM_MANUAL": 1}},
            {"material_balances": {ANTISERUM: 199, "COMBAT_MANUAL_I": 50}},
            {"confirmed_upgrades": 3},
            {"reset_guard_active": True},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(hero_evolution_authorizeable(replace(before, **changes)))

    def test_evolution_spec_uses_closed_vector_without_incompatible_scalar_sum(self):
        before = evolution_observation(confirmed_upgrades=1)
        spec = hero_evolution_spec(before)
        self.assertEqual(spec.action_kind, "HERO_EVOLUTION_STANDARD")
        self.assertEqual(spec.expected_source_screen, EVOLUTION_SCREEN)
        self.assertEqual(spec.subject, "Wali")
        self.assertEqual(spec.quantity, 1)
        self.assertIsNone(spec.resource_or_currency)
        self.assertIsNone(spec.maximum_cost)
        self.assertFalse(spec.free_only)
        self.assertEqual(spec.allowed_confirmation_dialogs, ())
        self.assertEqual(
            spec.semantic_preconditions,
            (
                "product_id=hero_upgrade",
                "product_revision=hero_upgrade-v3",
                "reset_identity=reset-17",
                "confirmed_upgrades=1",
                "next_upgrade_ordinal=2",
                "hero_identity=Wali",
                "hero_selected=true",
                "current_level=10",
                "evolution_cap=10",
                "next_evolution_cap=20",
                "target_identity=hero-evolve",
                "control_class=EVOLVE",
                "single_standard_evolution=true",
                "bulk_upgrade=false",
                "standard_materials_only=true",
                "material_cost.ANTISERUM=200",
                "material_balance.ANTISERUM=1000",
                "material_cost.COMBAT_MANUAL_I=30",
                "material_balance.COMBAT_MANUAL_I=50",
                "stable_selected_state=true",
                "native_target_evidence=true",
                "reset_action=false",
            ),
        )

    def test_evolution_named_receipt_proves_manual_use_without_fabricated_spend(self):
        before = evolution_observation(confirmed_upgrades=2)
        after = settled(
            before,
            evolution_cap=20,
            confirmed_upgrades=2,
            material_balances={ANTISERUM: 800},
            spent_materials={ANTISERUM: 200},
            material_usage_receipts=("COMBAT_MANUAL_I",),
            evidence_refs=("synthetic:manual-toast", "synthetic:wali-settled"),
        )
        self.assertEqual(after.spent_materials, {ANTISERUM: 200})
        self.assertTrue(hero_evolution_postcondition_verified(before, after))

    def test_evolution_manual_decrement_or_exact_numeric_receipt_also_proves_use(self):
        before = evolution_observation()
        decremented = settled(
            before,
            evolution_cap=20,
            confirmed_upgrades=0,
            material_balances={ANTISERUM: 800, "COMBAT_MANUAL_I": 20},
            spent_materials={ANTISERUM: 200},
        )
        self.assertTrue(hero_evolution_postcondition_verified(before, decremented))
        numeric = settled(
            before,
            evolution_cap=20,
            confirmed_upgrades=0,
            material_balances={ANTISERUM: 800},
            spent_materials={ANTISERUM: 200, "COMBAT_MANUAL_I": 30},
        )
        self.assertTrue(hero_evolution_postcondition_verified(before, numeric))

    def test_evolution_unknown_or_contradictory_material_settlement_is_not_verified(self):
        before = evolution_observation()
        valid_receipt = settled(
            before,
            evolution_cap=20,
            confirmed_upgrades=0,
            material_balances={ANTISERUM: 800},
            spent_materials={ANTISERUM: 200},
            material_usage_receipts=("COMBAT_MANUAL_I",),
            evidence_refs=("synthetic:manual-toast", "synthetic:wali-settled"),
        )
        self.assertFalse(
            hero_evolution_postcondition_verified(
                before,
                replace(valid_receipt, material_usage_receipts=()),
            )
        )
        self.assertFalse(
            hero_evolution_postcondition_verified(
                before,
                replace(
                    valid_receipt,
                    material_balances={ANTISERUM: 800, "COMBAT_MANUAL_I": 50},
                ),
            )
        )
        self.assertFalse(
            hero_evolution_postcondition_verified(before, replace(valid_receipt, evolution_cap=19))
        )
        self.assertFalse(
            hero_evolution_postcondition_verified(before, replace(valid_receipt, confirmed_upgrades=1))
        )
        self.assertFalse(
            hero_evolution_postcondition_verified(
                before,
                replace(valid_receipt, material_usage_receipts=("UNKNOWN_MATERIAL",)),
            )
        )
        self.assertFalse(
            hero_evolution_postcondition_verified(
                before,
                replace(valid_receipt, evidence_refs=("synthetic:manual-toast",)),
            )
        )

    def test_standard_manual_vocabulary_is_closed(self):
        self.assertEqual(
            STANDARD_MANUALS,
            (
                "COMBAT_MANUAL_I",
                "COMBAT_MANUAL_II",
                "COMBAT_MANUAL_III",
                "COMBAT_MANUAL_IV",
                "COMBAT_MANUAL_V",
            ),
        )
        for manual in STANDARD_MANUALS[1:]:
            before = evolution_observation(
                material_costs={ANTISERUM: 7, manual: 2},
                material_balances={ANTISERUM: 7, manual: 2},
            )
            self.assertTrue(hero_evolution_authorizeable(before))


if __name__ == "__main__":
    unittest.main()
