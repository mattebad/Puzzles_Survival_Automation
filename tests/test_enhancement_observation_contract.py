from __future__ import annotations

import unittest

from scripts import pnsctl
from scripts.flow_delivery_enhancement_bluestacks import _observation
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    enhancement_authorizeable,
    enhancement_bluestacks_authorizeable,
)


def _native_payload(*, slots=True) -> dict[str, object]:
    payload: dict[str, object] = {
        "screen_state": "COMMANDER_INFO",
        "selected_tab": "GEAR",
        "selected_item_kind": "GEAR",
        "selected_item_identity": "s.o.f suit",
        "item_equipped": True,
        "item_level": 18,
        "target_identity": "enhancement-confirm",
        "target_roi": [452, 1160, 725, 1250],
        "panel_bounds": [0, 0, 800, 1280],
        "control_class": "ENHANCE",
        "enhance_control_visible": True,
        "action_mode": "ENHANCE",
        "material_identity": "gear-material-one-star",
        "material_known": True,
        "material_available": True,
        "material_star": 1,
        "material_quantity": 1,
        "quantity": 1,
        "material_inventory_count": 1,
        "item_exp_current": 10,
        "item_exp_required": 260000,
        "item_exp_preview": 20,
        "selection_baseline_frame_sha256": "1" * 64,
        "selection_baseline_evidence_ref": "frames/baseline.png",
        "game_day_id": "local-2026-10-29-enhancement-family",
        "target_provenance": BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        "runtime_profile_id": BLUESTACKS_RUNTIME_PROFILE_ID,
    }
    if slots:
        payload["material_slot_facts"] = [[0, 1, 1, 1], [1, 3, 0, 2]]
    return payload


class EnhancementObservationContractTests(unittest.TestCase):
    def test_native_json_slot_arrays_are_normalized_to_immutable_tuples(self):
        observation = _observation(_native_payload(), "native")
        self.assertEqual(
            observation.material_slot_facts,
            ((0, 1, 1, 1), (1, 3, 0, 2)),
        )

    def test_native_observation_without_typed_facts_is_evidence_required(self):
        payload = _native_payload(slots=False)
        with self.assertRaisesRegex(pnsctl.OperatorError, "evidence_required"):
            _observation(payload, "legacy native")

    def test_native_slot_facts_reject_duplicate_or_invalid_cells(self):
        for cells in (
            [[0, 1, 0, 1], [0, 3, 0, 2]],
            [[0, 1, 2, 1]],
            [[0, True, 0, 1]],
        ):
            with self.subTest(cells=cells):
                payload = _native_payload()
                payload["material_slot_facts"] = cells
                with self.assertRaisesRegex(pnsctl.OperatorError, "evidence_required"):
                    _observation(payload, "invalid native")

    def test_selected_native_observation_requires_a_genuine_baseline_and_preview(self):
        for changes in (
            {"item_exp_preview": None},
            {"item_exp_preview": True},
            {"item_exp_preview": 10},
            {"item_exp_preview": 260000},
            {"selection_baseline_frame_sha256": "not-a-hash"},
            {"selection_baseline_evidence_ref": None},
        ):
            with self.subTest(changes=changes):
                payload = _native_payload()
                payload.update(changes)
                with self.assertRaisesRegex(pnsctl.OperatorError, "evidence_required"):
                    _observation(payload, "selected native")

    def test_zero_selected_native_observation_has_no_preview_authority(self):
        payload = _native_payload()
        payload.update(
            item_equipped=False, quantity=0, material_quantity=0,
            material_slot_facts=[[0, 1, 0, 1], [1, 3, 0, 2]],
            item_exp_preview=None, selection_baseline_frame_sha256=None,
            selection_baseline_evidence_ref=None,
        )
        observation = _observation(payload, "zero native")
        self.assertIsNone(observation.item_exp_preview)
        self.assertFalse(observation.item_equipped)

    def test_retired_bliss_observation_parses_but_is_never_authorized(self):
        payload = _native_payload(slots=False)
        payload["target_provenance"] = "bliss-native"
        payload["runtime_profile_id"] = "pns-blissos-poc-virgl-800x1280-v1"
        payload.pop("item_exp_current")
        payload.pop("item_exp_required")
        observation = _observation(payload, "legacy bliss")
        self.assertEqual(observation.material_slot_facts, ())
        self.assertIsNone(observation.item_exp_current)
        self.assertFalse(enhancement_authorizeable(observation))
        self.assertFalse(enhancement_bluestacks_authorizeable(observation))


if __name__ == "__main__":
    unittest.main()
