from __future__ import annotations

import copy
import hashlib
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts.flow_delivery_enhancement_bluestacks import (
    _replay_category_observations,
    _semantic_stage_for_phase,
)
from tests.support.enhancement_replay import CausalReplayFixture

from tests.support.environment import requires_tesseract

class EnhancementSemanticStageMappingTests(unittest.TestCase):
    def test_existing_phases_use_their_route_recognizer_contract(self):
        cases = {
            "home-to-commander-immediate-post": "tab",
            "home-to-commander-settled": "tab",
            "select-enhancement-category-immediate-before": "tab",
            "select-enhancement-category-immediate-post": "item",
            "select-equipped-enhancement-item-settled-1": "item",
            "select-exact-one-star-material-settled": "material",
            "apply-quantity-selection-settled": "material",
            "use-one-star-enhancer-immediate-before": "material",
            "use-one-star-enhancer-immediate-post": "post",
            "enhancement-settle-0": "post",
            "commander-to-home-terminal-immediate-before": "tab",
            "commander-to-home-terminal-settled": "home",
            "family-home-terminal": "home",
        }
        for phase, expected in cases.items():
            with self.subTest(phase=phase):
                self.assertEqual(_semantic_stage_for_phase(phase), expected)

    def test_unknown_phase_is_not_guessed_from_a_generic_settle_token(self):
        self.assertIsNone(_semantic_stage_for_phase("unrelated-settled-phase"))
        self.assertIsNone(_semantic_stage_for_phase("commander-animation-settled"))

    def test_frozen_navigation_phases_use_persisted_detail_state(self):
        self.assertEqual(_semantic_stage_for_phase(
            "return-home-source-0", detail_state="item_modal"
        ), "item")
        self.assertEqual(_semantic_stage_for_phase(
            "commander-return-1-settled-1", detail_state="commander_overview"
        ), "tab")
        self.assertEqual(_semantic_stage_for_phase(
            "return-home-2-immediate-post", detail_state="home"
        ), "home")
        self.assertEqual(_semantic_stage_for_phase(
            "return-home-source-0", detail_state="enhancement_post"
        ), "post")
        self.assertEqual(_semantic_stage_for_phase(
            "return-home-source-0", detail_state="enhancement_panel"
        ), "material")
        self.assertIsNone(_semantic_stage_for_phase("return-home-source-0"))

    def test_commander_continuation_replays_its_actual_modal_or_overview(self):
        self.assertEqual(_semantic_stage_for_phase("commander-source", detail_state="item_modal"), "item")
        self.assertEqual(_semantic_stage_for_phase("commander-source", detail_state="commander_overview"), "tab")
        self.assertEqual(_semantic_stage_for_phase("commander-source", detail_state="enhancement_panel"), "material")
        self.assertIsNone(_semantic_stage_for_phase("commander-source", detail_state="unrecognized"))


class EnhancementCausalReplayTests(CausalReplayFixture, unittest.TestCase):

    def test_exact_same_session_chain_replays_selected_before_and_committed_post(self):
        self.assertTrue(self.verify())
        self.assertIn(("gear", "modal", "item"), self.parser_calls)
        self.assertIn(("gear", "quantity", "material"), self.parser_calls)
        self.assertIn(("gear", "successor", "post"), self.parser_calls)

    def test_unknown_positive_phase_cannot_be_skipped(self):
        self.result["enhancement_result"]["stages"].append({
            "kind": "recognition", "stage": "unmapped-positive-phase", "recognized": True,
            "variant": "module", "frame_sha256": self.home_hash})
        self.assertFalse(self.verify())

    def test_unbound_equipped_flag_or_changed_baseline_fails(self):
        proof = self.result["enhancement_result"]["category_results"][0]
        original = copy.deepcopy(proof["before_observation"])
        for changes in (
            {"evidence_refs": original["evidence_refs"][:1]},
            {"item_exp_current": 20},
            {"item_exp_preview": 21},
            {"selection_baseline_frame_sha256": self.digests["gear", "modal"]},
            {"selection_baseline_evidence_ref": str(self.paths["chip", "baseline"])},
        ):
            with self.subTest(changes=changes):
                proof["before_observation"] = {**original, **changes}
                self.assertFalse(self.verify())
        proof["before_observation"] = original

    def test_source_target_dispatch_and_post_order_are_causal(self):
        original = copy.deepcopy(self.rows)
        dispatch = next(i for i, row in enumerate(self.rows) if row.get("target_identity") == "material-select:gear")
        capture = dispatch - 1
        cases = (
            (dispatch, {"source_sha256": self.digests["chip", "baseline"]}),
            (dispatch, {"target_roi": (191, 610, 280, 700)}),
            (dispatch, {"point": (0, 0)}),
            (dispatch, {"execute": False}),
            (dispatch, {"target_identity": "material-select:chip"}),
            (capture, {"path": str(self.paths["chip", "baseline"])}),
            (capture, {"captured_monotonic": float("nan")}),
            (capture, {"timestamp": "2026-10-30T14:00:00+00:00"}),
        )
        for index, changes in cases:
            with self.subTest(changes=changes):
                self.rows = copy.deepcopy(original)
                self.rows[index].update(changes)
                self.assertFalse(self.verify())
        self.rows = copy.deepcopy(original)
        self.rows.insert(dispatch, copy.deepcopy(self.rows[dispatch]))
        self.assertFalse(self.verify())
        self.rows = copy.deepcopy(original)
        self.rows.insert(dispatch, copy.deepcopy(self.rows[capture]))
        self.assertFalse(self.verify())
        self.rows = copy.deepcopy(original)
        after_use = next(i for i, row in enumerate(self.rows) if row.get("target_identity") == "enhancement-use") + 1
        self.rows.insert(after_use, copy.deepcopy(self.rows[dispatch]))
        self.assertFalse(self.verify())

    def test_preview_or_stock_claim_cannot_substitute_for_a_committed_effect(self):
        proof = self.result["enhancement_result"]["category_results"][0]
        original = copy.deepcopy(proof["successor_observation"])
        for changes in (
            {"item_exp_current": 19},
            {"item_exp_current": 21},
            {"item_level": 19},
            {"item_exp_preview": 20},
            {"material_inventory_count": 9562},
            {"material_slot_facts": ((0, 4, 0, 1), (1, 1, 0, 9561), (2, 0, 0, 100))},
        ):
            with self.subTest(changes=changes):
                proof["successor_observation"] = {**original, **changes}
                self.assertFalse(self.verify())
        proof["successor_observation"] = original

    def test_actual_png_tamper_fails_even_when_retained_semantic_fields_match(self):
        self.paths["gear", "baseline"].write_bytes(self.paths["chip", "baseline"].read_bytes())
        self.assertFalse(self.verify())

    def test_frame_changed_after_lookup_is_still_rejected_at_semantic_use(self):
        commander = self.commander
        changed = False

        def change_later_frame(frame, **kwargs):
            nonlocal changed
            if not changed and self.roles[kwargs["source_frame_sha256"]] == ("gear", "modal"):
                self.paths["module", "successor"].write_bytes(self.paths["gear", "successor"].read_bytes())
                changed = True
            return commander(frame, **kwargs)

        self.commander = change_later_frame
        self.assertFalse(self.verify())
        self.assertTrue(changed)

    def add_unknown_immediate_post(self):
        image = np.full((1280, 800, 3), 51, dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        path = self.session / "frames" / "gear-immediate-post.png"
        path.write_bytes(encoded.tobytes())
        digest = hashlib.sha256(encoded.tobytes()).hexdigest()
        self.roles[digest] = ("gear", "immediate")
        use = next(i for i, row in enumerate(self.rows) if row.get("target_identity") == "enhancement-use")
        self.rows.insert(use + 1, {
            "type": "capture", "path": str(path), "sha256": digest,
            "captured_monotonic": 9.25, "timestamp": self.timestamp(9.25),
        })
        self.actions[0].update(immediate_post_sha256=digest, after_sha256=digest)
        return digest

    def test_delayed_effect_preserves_the_unknown_immediate_post_envelope(self):
        self.add_unknown_immediate_post()
        self.assertTrue(self.verify())

    def test_confirm_envelope_cannot_omit_the_first_post_or_claim_recovery(self):
        self.add_unknown_immediate_post()
        original = copy.deepcopy(self.actions[0])
        for changes in (
            {"before_sha256": self.digests["gear", "baseline"]},
            {"immediate_post_sha256": self.digests["gear", "successor"]},
            {"after_sha256": self.digests["gear", "successor"]},
            {"recovery_used": True},
            {"action_key": "enhancement:gear:other-confirm:test"},
        ):
            with self.subTest(changes=changes):
                self.actions[0] = {**original, **changes}
                self.assertFalse(self.verify())
        self.actions[0] = original
        self.actions.append(copy.deepcopy(original))
        self.assertFalse(self.verify())
        self.actions.pop()
        self.actions.clear()
        self.assertFalse(self.verify())

    @requires_tesseract
    def test_real_selected_preview_does_not_prove_a_committed_resource_effect(self):
        from scripts import pnsctl
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        from scripts.enhancement_bluestacks import (
            recognize_commander_stage, recognize_selection_context,
        )

        # These immutable native fixtures are copied into an OFFLINE synthetic
        # journal. It proves parser integration, never a live same-run receipt.
        fixtures = Path(__file__).parent / "fixtures" / "enhancement_item_modal"
        names = {
            "modal": "native-gear-sof-suit-stat-bullet-20261029.png",
            "baseline": "native-gear-no-material-selected-20261029.png",
            "quantity": "native-gear-quantity-one-20261029.png",
            "current": "native-gear-one-material-preview-20261029.png",
            "successor": "native-gear-no-material-selected-20261029.png",
        }
        captures = {}
        for number, (role, name) in enumerate(names.items(), start=1):
            path = self.paths["gear", role]
            path.write_bytes((fixtures / name).read_bytes())
            captures[role] = captured_native_frame_from_png(
                path.read_bytes(), captured_monotonic=number * 2, path=path,
            )
            old_hash = self.digests["gear", role]
            self.digests["gear", role] = captures[role].sha256
            for row in self.rows:
                if row.get("path") == str(path):
                    row["sha256"] = captures[role].sha256
                if row.get("source_sha256") == old_hash:
                    row["source_sha256"] = captures[role].sha256
        selected = recognize_selection_context(
            captures["current"], modal=captures["modal"], baseline=captures["baseline"],
            quantity=captures["quantity"], variant="gear", game_day_id=self.reset,
        )
        self.assertTrue(selected.recognized, selected.reason)
        self.assertEqual(selected.observation.item_exp_current, 10)
        self.assertEqual(selected.observation.item_exp_preview, 20)
        source = captures["successor"]
        post = recognize_commander_stage(
            source.frame, variant="gear", stage="post", source_frame_sha256=source.sha256,
            evidence_ref=source.path, game_day_id=self.reset,
        )
        self.assertTrue(post.recognized, post.reason)
        targets = selected.diagnostics["selection_context_targets"]
        for row in self.rows:
            target = {
                "open-enhance:gear": targets["modal_enhance"],
                "material-select:gear": targets["baseline_card"],
                "quantity-use": targets["quantity_use"],
                "enhancement-use": selected.observation.target_roi,
            }.get(row.get("target_identity"))
            if target is not None and str(row.get("action_key", "")).startswith("enhancement:gear:"):
                row["target_roi"] = target
                row["point"] = ((target[0] + target[2]) // 2, (target[1] + target[3]) // 2)
        proof = self.result["enhancement_result"]["category_results"][0]
        proof.update(
            source_frame_sha256=selected.observation.source_frame_sha256,
            before_observation=asdict(selected.observation), successor_observation=asdict(post.observation),
        )
        self.actions[0].update(
            before_sha256=selected.observation.source_frame_sha256,
            immediate_post_sha256=post.observation.source_frame_sha256,
            after_sha256=post.observation.source_frame_sha256,
        )
        with self.assertRaisesRegex(pnsctl.OperatorError, "committed effect"):
            _replay_category_observations(
                proof, variant="gear", reset=self.reset, session=self.session,
                rows=self.rows, frame_hashes=set(self.digests.values()) | {self.home_hash},
                actions=self.actions,
            )


if __name__ == "__main__":
    unittest.main()
