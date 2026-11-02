"""Pure BlueStacks material facts; these records never dispatch native input."""
from dataclasses import replace
import unittest

from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE, BLUESTACKS_RUNTIME_PROFILE_ID,
    ENHANCEMENT_SCREEN, EnhancementObservation,
    enhancement_bluestacks_authorizeable, enhancement_bluestacks_postcondition_verified,
)


def selected(variant="gear"):
    return EnhancementObservation(screen_state=ENHANCEMENT_SCREEN,
        selected_tab=variant.upper(), selected_item_kind=variant.upper(),
        selected_item_identity=f"observed-{variant}-item", item_equipped=True, item_level=18,
        target_identity="enhancement-confirm", target_roi=(450, 1160, 720, 1250),
        panel_bounds=(0, 0, 800, 1280), control_class="ENHANCE", enhance_control_visible=True,
        action_mode="ENHANCE", material_identity=f"{variant}-material-one-star",
        material_known=True, material_available=True, material_star=1,
        material_quantity=1, quantity=1, material_inventory_count=27,
        item_exp_current=95, item_exp_required=900, item_exp_preview=105,
        selection_baseline_frame_sha256="c" * 64,
        selection_baseline_evidence_ref="unit-model/baseline.png",
        material_slot_facts=((0, 3, 0, 2), (1, 1, 1, 27), (2, 0, 0, 100)),
        game_day_id="current-reset", target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256="a" * 64, evidence_refs=("unit-model/selected.png",
            "unit-model/equipped-modal.png", "unit-model/baseline.png", "unit-model/quantity-one.png"),
        runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID)


def progressed(before):
    return replace(before, source_frame_sha256="b" * 64, evidence_refs=("unit-model/after.png",),
        item_exp_current=105, material_inventory_count=26, material_quantity=0, quantity=0,
        item_exp_preview=None, selection_baseline_frame_sha256=None, selection_baseline_evidence_ref=None,
        material_slot_facts=((0, 3, 0, 2), (1, 1, 0, 26), (2, 0, 0, 100)))


class NativeMaterialContractTests(unittest.TestCase):
    def test_all_three_require_observed_exp_and_exact_one_star_selection(self):
        for variant in ("gear", "chip", "module"):
            before = selected(variant)
            self.assertTrue(enhancement_bluestacks_authorizeable(before, variant=variant))
            for changes in ({"material_slot_facts": ()}, {"item_exp_current": None},
                    {"item_exp_required": None}, {"material_quantity": True}, {"quantity": True},
                    {"material_inventory_count": 26}, {"material_slot_facts": ((0, 1, 0, 27),)},
                    {"material_slot_facts": ((0, 1, 2, 27),)},
                    {"material_slot_facts": ((0, 1, 1, 27), (1, 3, 1, 2))},
                    {"material_slot_facts": ((0, 1, 1, 27), (1, 1, 0, 27))},
                    {"material_slot_facts": ((0, 1, 1, 27), (0, 3, 0, 2))},
                    {"item_exp_current": 900}, {"item_exp_required": True}):
                with self.subTest(variant=variant, changes=changes):
                    self.assertFalse(enhancement_bluestacks_authorizeable(replace(before, **changes), variant=variant))

    def test_legacy_or_claimed_quantity_one_cannot_replace_zero_selected_cells(self):
        before = selected()
        empty = replace(before, material_slot_facts=(), item_exp_current=None, item_exp_required=None)
        self.assertFalse(enhancement_bluestacks_authorizeable(empty))
        zero = replace(before, material_slot_facts=((0, 3, 0, 2), (1, 1, 0, 27), (2, 0, 0, 100)))
        self.assertFalse(enhancement_bluestacks_authorizeable(zero))
        self.assertFalse(enhancement_bluestacks_postcondition_verified(zero, progressed(before)))

    def test_selection_requires_distinct_baseline_provenance_and_actual_preview(self):
        before = selected()
        for changes in (
                {"item_exp_preview": None}, {"item_exp_preview": True},
                {"item_exp_preview": 95}, {"item_exp_preview": 94},
                {"item_exp_preview": 900}, {"item_exp_preview": 901},
                {"selection_baseline_frame_sha256": None},
                {"selection_baseline_frame_sha256": "0" * 64},
                {"selection_baseline_frame_sha256": "not-a-sha256"},
                {"selection_baseline_frame_sha256": before.source_frame_sha256},
                {"selection_baseline_evidence_ref": None},
                {"selection_baseline_evidence_ref": "unit-model/forged-baseline.png"},
                {"selection_baseline_evidence_ref": "unit-model/selected.png"},
                {"evidence_refs": before.evidence_refs[:3]},
                {"evidence_refs": (before.evidence_refs[0], before.evidence_refs[2], before.evidence_refs[1], before.evidence_refs[3])},
                {"evidence_refs": (before.evidence_refs[0], before.evidence_refs[1], before.evidence_refs[2], before.evidence_refs[2])},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(enhancement_bluestacks_authorizeable(replace(before, **changes)))

    def test_zero_selected_observation_has_no_preview_or_baseline_authority(self):
        zero = replace(progressed(selected()), item_exp_current=95, material_inventory_count=27,
            material_slot_facts=((0, 3, 0, 2), (1, 1, 0, 27), (2, 0, 0, 100)), item_equipped=False)
        self.assertIsNone(zero.item_exp_preview)
        self.assertIsNone(zero.selection_baseline_frame_sha256)
        self.assertIsNone(zero.selection_baseline_evidence_ref)
        self.assertFalse(enhancement_bluestacks_authorizeable(zero))

    def test_success_needs_exact_inventory_delta_and_exp_progress_for_same_item(self):
        for variant in ("gear", "chip", "module"):
            before = selected(variant)
            after = progressed(before)
            self.assertTrue(enhancement_bluestacks_postcondition_verified(before, after, variant=variant))
            for changes in ({"item_exp_current": 95}, {"item_exp_current": 104},
                    {"item_exp_current": 106}, {"item_exp_preview": 105},
                    {"selection_baseline_frame_sha256": "c" * 64},
                    {"selection_baseline_evidence_ref": "unit-model/baseline.png"},
                    {"material_slot_facts": ()},
                    {"material_inventory_count": 25, "material_slot_facts": ((0, 3, 0, 2), (1, 1, 0, 25), (2, 0, 0, 100))},
                    {"material_slot_facts": ((0, 3, 0, 1), (1, 1, 0, 26), (2, 0, 0, 100))},
                    {"material_slot_facts": ((0, 3, 0, 2), (1, 1, 1, 26), (2, 0, 0, 100))},
                    {"selected_item_identity": "another-item"}, {"game_day_id": "another-day"},
                    {"overlay_state": "unknown"}, {"source_frame_sha256": "0" * 64}):
                with self.subTest(variant=variant, changes=changes):
                    self.assertFalse(enhancement_bluestacks_postcondition_verified(before, replace(after, **changes), variant=variant))
            self.assertFalse(enhancement_bluestacks_postcondition_verified(before,
                replace(after, source_frame_sha256=before.source_frame_sha256), variant=variant))

    def test_unchanged_inventory_exp_is_never_a_success_even_with_claimed_result(self):
        before = selected()
        unchanged = replace(before, quantity=0, material_quantity=0,
            material_slot_facts=((0, 3, 0, 2), (1, 1, 0, 27), (2, 0, 0, 100)),
            enhancement_result_visible=True, result_identity=before.selected_item_identity,
            result_spatially_associated=True)
        self.assertFalse(enhancement_bluestacks_postcondition_verified(before, unchanged))
        self.assertFalse(enhancement_bluestacks_postcondition_verified(before, before))

    def test_level_change_cannot_bypass_measured_preview_even_with_exact_inventory_deduction(self):
        for variant in ("gear", "chip", "module"):
            before = selected(variant)
            after = progressed(before)
            self.assertTrue(enhancement_bluestacks_postcondition_verified(before, after, variant=variant))
            # Every candidate still has owned-1, selected0 and unchanged other
            # material cells. A level change is outside the proven UI contract,
            # even if its EXP happens to equal the observed preview.
            for level, exp, required in ((19, 2, 1000), (19, 105, 900), (17, 105, 900), (19, 106, 900)):
                with self.subTest(variant=variant, level=level, exp=exp):
                    candidate = replace(after, item_level=level, item_exp_current=exp, item_exp_required=required)
                    self.assertFalse(enhancement_bluestacks_postcondition_verified(before, candidate, variant=variant))

    def test_new_facts_alone_do_not_replace_native_provenance(self):
        before = selected()
        self.assertFalse(enhancement_bluestacks_authorizeable(replace(before,
            target_provenance="unknown", evidence_refs=("synthetic:record",))))


if __name__ == "__main__":
    unittest.main()
