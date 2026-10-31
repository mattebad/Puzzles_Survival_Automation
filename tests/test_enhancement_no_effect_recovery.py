from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import pnsctl
import scripts.flow_delivery_enhancement_bluestacks as delivery
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    EnhancementObservation,
)


RESET = "local-2026-10-29-enhancement-family"
KEY = "enhancement:gear:enhancement-use:original"


def _frame(session: Path, name: str, payload: bytes | None = None) -> tuple[str, str]:
    if payload is None:
        ok, encoded = cv2.imencode(".png", np.full((1280, 800, 3), 7, dtype=np.uint8))
        if not ok:
            raise AssertionError("native frame did not encode")
        payload = encoded.tobytes()
    reference = f"frames/{name}.png"
    path = session / reference
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return reference, hashlib.sha256(payload).hexdigest()


def _observation(session: Path, reference: str, digest: str) -> dict[str, object]:
    return asdict(EnhancementObservation(
        screen_state="COMMANDER_INFO", selected_tab="GEAR", selected_item_kind="GEAR",
        selected_item_identity="s.o.f suit", item_equipped=False, item_level=18,
        target_identity="enhancement-confirm", target_roi=(485, 1180, 651, 1245),
        panel_bounds=(0, 0, 800, 1280), control_class="ENHANCE", enhance_control_visible=True,
        action_mode="ENHANCE", material_identity="gear-material-one-star", material_known=True,
        material_available=True, material_star=1, material_quantity=0, quantity=0,
        material_inventory_count=9562, game_day_id=RESET,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=digest, evidence_refs=(str(session / reference),),
        overlay_state="none", runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
        item_exp_current=10, item_exp_required=260000,
        material_slot_facts=((0, 4, 0, 2), (1, 1, 0, 9562), (2, 0, 0, 100)),
    ))


def _capture(reference: str, digest: str, second: int, monotonic: float) -> dict[str, object]:
    return {"type": "capture", "sha256": digest, "path": reference,
            "captured_monotonic": monotonic,
            "timestamp": f"2026-10-29T12:00:{second:02d}+00:00"}


def _state(root: Path, payload: bytes | None = None):
    original, recovery = root / "original", root / "recovery"
    original.mkdir()
    recovery.mkdir()
    p_ref, p_hash = _frame(original, "p", payload)
    i_ref, i_hash = _frame(original, "i", payload)
    r1_ref, r1_hash = _frame(recovery, "r1", payload)
    r2_ref, r2_hash = _frame(recovery, "r2", payload)
    before = _observation(original, p_ref, p_hash)
    immediate = _observation(original, i_ref, i_hash)
    fresh = _observation(recovery, r1_ref, r1_hash)
    later = _observation(recovery, r2_ref, r2_hash)
    legacy_before = dict(before, quantity=1, material_quantity=1, item_equipped=True)
    for key in ("item_exp_current", "item_exp_required", "material_slot_facts"):
        legacy_before.pop(key)
    # Retained wrong facts remain unchanged; only the new receipt replays the PNG.
    legacy_before["target_roi"] = [452, 1160, 725, 1250]
    attempt = {
        "variant": "gear", "status": "dispatch_bearing_unresolved",
        "resource_affecting_dispatch_count": 1, "resource_affecting_action_key": KEY,
        "source_frame_sha256": p_hash, "before_observation": legacy_before,
        "successor_observation": None, "runtime_session": str(original),
    }
    attempt = json.loads(json.dumps(attempt))
    result = {
        "flow_id": delivery.FLOW_ID, "variant": "family",
        "serial": pnsctl.BLUESTACKS_SERIAL, "native_width": 800, "native_height": 1280,
        "actions": [{"label": "use-one-star-enhancer", "action_key": KEY,
                     "before_sha256": p_hash, "immediate_post_sha256": i_hash,
                     "after_sha256": i_hash}],
        "enhancement_result": {"category_results": [attempt]},
    }
    (original / "flow-delivery-result.json").write_text(json.dumps(result), encoding="utf-8")
    original_rows = [
        _capture(p_ref, p_hash, 0, 10.0),
        {"type": "dispatch", "action_key": KEY, "target_identity": "enhancement-use",
         "resource_affecting": True, "source_sha256": p_hash, "execute": True,
         "target_roi": legacy_before["target_roi"], "point": [588, 1205],
         "timestamp": "2026-10-29T12:00:01+00:00"},
        _capture(i_ref, i_hash, 2, 12.0),
    ]
    recovery_rows = [_capture(r1_ref, r1_hash, 10, 20.0), _capture(r2_ref, r2_hash, 11, 21.0)]
    _rows(original / "events.jsonl", original_rows)
    _rows(recovery / "events.jsonl", recovery_rows)
    receipt = {
        "proof_kind": "zero_selected_confirm",
        "semantic_replay_reason": "legacy_static_selected_quantity_shortcut_rejected",
        "original_action_key": KEY, "original_runtime_session": str(original),
        "recovery_session_directory": str(recovery),
        "original_source_frame_sha256": p_hash, "original_immediate_post_frame_sha256": i_hash,
        "immediate_recovery_frame_sha256": r1_hash, "later_recovery_frame_sha256": r2_hash,
        "original_before_observation": before, "original_immediate_post_observation": immediate,
        "immediate_recovery_observation": fresh, "later_recovery_observation": later,
        "reset_identity": RESET, "input_count": 0, "dispatch_count": 0,
        "resource_affecting_dispatch_count": 0,
    }
    return attempt, receipt, original, recovery


def _rows(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _read_rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _historical_chip(base: Path, day="local-2026-08-18-enhancement-gear", *, pending=False):
    session = base / "legacy-chip-runtime"
    session.mkdir(parents=True)
    reference, digest = _frame(session, "before")
    before = _observation(session, reference, digest)
    before.update(selected_tab="CHIP", selected_item_kind="CHIP", selected_item_identity="fighter chip",
                  game_day_id=day, material_identity="chip-material-one-star", item_equipped=True,
                  quantity=1, material_quantity=1)
    for field in ("item_exp_current", "item_exp_required", "material_slot_facts"):
        before.pop(field)
    after = dict(before, quantity=0, material_quantity=0)
    key = "enhancement:chip:enhancement-use:historical"
    entry = {"variant": "chip", "status": "dispatch_bearing_unresolved" if pending else "completed",
             "resource_affecting_dispatch_count": 1, "resource_affecting_action_key": key,
             "source_frame_sha256": digest, "before_observation": before,
             "successor_observation": None if pending else after, "runtime_session": str(session)}
    entry = json.loads(json.dumps(entry))
    (session / "flow-delivery-result.json").write_text(json.dumps({
        "flow_id": delivery.FLOW_ID, "enhancement_result": {"category_results": [entry]},
    }), encoding="utf-8")
    _rows(session / "events.jsonl", [{"type": "dispatch", "action_key": key,
        "target_identity": "enhancement-use", "resource_affecting": True,
        "source_sha256": digest, "execute": True}])
    (base / "family-progress.json").write_text(json.dumps({
        "flow_id": delivery.FLOW_ID, "categories": {"chip": entry},
    }), encoding="utf-8")
    return entry


class EnhancementNoEffectRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.replays = []

        def replay(frame, *, variant, stage, source_frame_sha256, evidence_ref, game_day_id):
            del frame
            self.replays.append((variant, stage, Path(evidence_ref)))
            observation = delivery._observation(_observation(
                Path(evidence_ref).parent.parent,
                "frames/" + Path(evidence_ref).name,
                source_frame_sha256,
            ), "test replay")
            return SimpleNamespace(recognized=True, observation=replace(observation, game_day_id=game_day_id))

        self.parser_patch = patch("scripts.enhancement_bluestacks.recognize_commander_stage", replay)
        self.parser_patch.start()
        self.addCleanup(self.parser_patch.stop)

    def _pending(self, root, attempt):
        path = root / "family-progress.json"
        path.write_text(json.dumps({"flow_id": delivery.FLOW_ID, "categories": {"gear": attempt}}), encoding="utf-8")
        return path

    def _recover(self, root):
        attempt, receipt, original, recovery = _state(root)
        self._pending(root, attempt)
        delivery._reconcile_recovery_no_effect(root, "gear", {
            "status": "recovered_no_effect", "proof_kind": "zero_selected_confirm",
            "input_count": 0, "dispatch_count": 0, "resource_affecting_dispatch_count": 0,
            "no_effect_receipt": receipt,
        }, recovery_session=recovery)
        return attempt, receipt, original, recovery

    def test_zero_selected_recovery_replays_every_png_and_preserves_original_and_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reservation = root / "reservation-gear.json"
            reservation.write_bytes(b"retained reservation")
            attempt, receipt, original, recovery = self._recover(root)
            entry = json.loads((root / "family-progress.json").read_bytes())["categories"]["gear"]
            self.assertEqual(entry["status"], "confirmed_no_effect")
            self.assertEqual(entry["original_attempt"], json.loads(json.dumps(attempt)))
            self.assertEqual(entry["original_attempt"]["before_observation"]["quantity"], 1)
            self.assertEqual(entry["no_effect_receipt"]["original_before_observation"]["quantity"], 0)
            self.assertEqual(reservation.read_bytes(), b"retained reservation")
            self.assertEqual(len(self.replays), 4)
            self.assertEqual(json.loads((recovery / "no-effect-recovery-receipt.json").read_bytes()), json.loads(json.dumps(receipt)))
            self.assertEqual(delivery._load_family_progress(root, reset_identity=RESET), {})
            self.assertEqual(json.loads((original / "flow-delivery-result.json").read_bytes())["enhancement_result"]["category_results"][0], json.loads(json.dumps(attempt)))

    def test_json_facts_cannot_replace_independent_png_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            attempt, receipt, _original, _recovery = _state(root)
            with patch("scripts.enhancement_bluestacks.recognize_commander_stage", return_value=SimpleNamespace(recognized=False, observation=None)):
                with self.assertRaisesRegex(pnsctl.OperatorError, "replay"):
                    delivery._validate_zero_selected_no_effect_receipt(receipt, attempt, variant="gear", reset_identity=RESET)

    def test_same_label_confirms_bind_only_the_exact_original_no_effect_source(self):
        with tempfile.TemporaryDirectory() as folder:
            attempt, receipt, original, _recovery = _state(Path(folder))
            path = original / "flow-delivery-result.json"
            result = json.loads(path.read_bytes())
            original_action = dict(result["actions"][0])
            result["actions"].insert(0, {
                **original_action, "before_sha256": "b" * 64,
                "action_key": "enhancement:chip:enhancement-use:earlier-confirm",
            })
            path.write_text(json.dumps(result), encoding="utf-8")
            delivery._validate_zero_selected_no_effect_receipt(receipt, attempt, variant="gear", reset_identity=RESET)
            result["actions"].append(original_action)
            path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaises(pnsctl.OperatorError):
                delivery._validate_zero_selected_no_effect_receipt(receipt, attempt, variant="gear", reset_identity=RESET)
            result["actions"].pop()
            result["actions"][1]["action_key"] = "enhancement:gear:enhancement-use:wrong-key"
            path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaises(pnsctl.OperatorError):
                delivery._validate_zero_selected_no_effect_receipt(receipt, attempt, variant="gear", reset_identity=RESET)

    def test_changed_facts_paths_clocks_or_inputs_reject_without_progress_mutation(self):
        changes = ("facts", "path", "missing_path", "after_hash", "same_capture", "clock", "later_input", "missing_key")
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                attempt, receipt, original, recovery = _state(root)
                progress = self._pending(root, attempt)
                retained = progress.read_bytes()
                if change == "facts":
                    for key in ("original_before_observation", "original_immediate_post_observation", "immediate_recovery_observation", "later_recovery_observation"):
                        receipt[key]["item_exp_current"] = 11
                elif change in ("path", "missing_path", "clock", "later_input"):
                    rows = _read_rows(recovery / "events.jsonl")
                    if change == "path": rows[0]["path"] = "frames/unrelated.png"
                    elif change == "missing_path": rows[0].pop("path")
                    elif change == "clock": rows[1]["captured_monotonic"] = float("nan")
                    else: rows.append({"type": "dispatch"})
                    _rows(recovery / "events.jsonl", rows)
                elif change == "after_hash":
                    result = json.loads((original / "flow-delivery-result.json").read_bytes())
                    result["actions"][0]["after_sha256"] = "f" * 64
                    (original / "flow-delivery-result.json").write_text(json.dumps(result), encoding="utf-8")
                elif change == "same_capture":
                    receipt["later_recovery_observation"]["evidence_refs"] = receipt["immediate_recovery_observation"]["evidence_refs"]
                else:
                    receipt.pop("original_action_key")
                    receipt["unrelated_extra"] = True
                with self.assertRaises(pnsctl.OperatorError):
                    delivery._reconcile_recovery_no_effect(root, "gear", {
                        "status": "recovered_no_effect", "proof_kind": "zero_selected_confirm",
                        "input_count": 0, "dispatch_count": 0, "resource_affecting_dispatch_count": 0,
                        "no_effect_receipt": receipt,
                    }, recovery_session=recovery)
                self.assertEqual(progress.read_bytes(), retained)
                self.assertFalse((recovery / "no-effect-recovery-receipt.json").exists())

    def test_selected_one_cannot_be_relabelled_as_no_effect(self):
        with tempfile.TemporaryDirectory() as folder:
            attempt, receipt, _original, _recovery = _state(Path(folder))
            for key in ("original_before_observation", "original_immediate_post_observation", "immediate_recovery_observation", "later_recovery_observation"):
                receipt[key]["quantity"] = receipt[key]["material_quantity"] = 1
                receipt[key]["material_slot_facts"] = ((0, 4, 0, 2), (1, 1, 1, 9562), (2, 0, 0, 100))
            with self.assertRaises(pnsctl.OperatorError):
                delivery._validate_zero_selected_no_effect_receipt(receipt, attempt, variant="gear", reset_identity=RESET)
            for key in ("original_before_observation", "original_immediate_post_observation", "immediate_recovery_observation", "later_recovery_observation"):
                receipt[key].update(
                    item_exp_preview=20,
                    selection_baseline_frame_sha256=receipt[key]["source_frame_sha256"],
                    selection_baseline_evidence_ref=receipt[key]["evidence_refs"][0],
                )
            with self.assertRaises(pnsctl.OperatorError):
                delivery._validate_zero_selected_no_effect_receipt(receipt, attempt, variant="gear", reset_identity=RESET)

    def test_continuation_claim_is_one_shot_and_preserves_history_on_new_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._recover(root)
            outer = root / "new-attempt"
            runtime = outer / "runtime"
            runtime.mkdir(parents=True)
            delivery._claim_no_effect_continuation(root, "gear", invocation_id="inv-1", session_directory=str(outer))
            with self.assertRaisesRegex(pnsctl.OperatorError, "already claimed"):
                delivery._claim_no_effect_continuation(root, "gear", invocation_id="inv-2", session_directory=str(outer))
            with self.assertRaisesRegex(pnsctl.OperatorError, "already claimed"):
                delivery._load_family_progress(root, reset_identity=RESET)
            new_key = "enhancement:gear:enhancement-use:new"
            delivery._persist_unresolved_dispatch(root, runtime, [{"type": "dispatch", "action_key": new_key, "target_identity": "enhancement-use", "resource_affecting": True}], None)
            entry = json.loads((root / "family-progress.json").read_bytes())["categories"]["gear"]
            self.assertEqual(entry["status"], "dispatch_bearing_unresolved")
            self.assertEqual(entry["resource_affecting_action_key"], new_key)
            self.assertEqual(len(entry["no_effect_history"]), 1)

    def test_unclaimed_or_identical_resource_cannot_supersede_resolved_attempt(self):
        for key in (KEY, "enhancement:gear:enhancement-use:new"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self._recover(root)
                with self.assertRaises(pnsctl.OperatorError):
                    delivery._persist_unresolved_dispatch(root, root / "new", [{"type": "dispatch", "action_key": key, "target_identity": "enhancement-use", "resource_affecting": True}], None)

    def test_writer_keeps_claimed_barrier_when_another_category_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._recover(root)
            outer = root / "new-attempt"
            outer.mkdir()
            delivery._claim_no_effect_continuation(root, "gear", invocation_id="inv-1", session_directory=str(outer))
            delivery._write_family_progress(root, {"category_results": [{"variant": "chip", "status": "completed", "resource_affecting_action_key": "enhancement:chip:new"}]})
            categories = json.loads((root / "family-progress.json").read_bytes())["categories"]
            self.assertIn("gear", categories)
            self.assertIsNotNone(categories["gear"]["continuation_claim"])

    def test_malformed_categories_are_operator_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "family-progress.json").write_text(json.dumps({"flow_id": delivery.FLOW_ID, "categories": {"gear": 5}}), encoding="utf-8")
            with self.assertRaises(pnsctl.OperatorError):
                delivery._read_family_progress_categories(root)

    def test_current_recovery_ignores_old_completion_but_normal_admission_keeps_unknown_barrier(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            attempt, _receipt, _original, _recovery = _state(root)
            base = root / "flow"
            _historical_chip(base)
            current = base / "occurrences" / RESET
            current.mkdir(parents=True)
            self._pending(current, attempt)
            original = {path: path.read_bytes() for path in base.rglob("*") if path.is_file()}
            self.assertEqual(delivery._select_family_state(base, RESET, recovery_variant="gear"), (current, RESET, {}))
            with self.assertRaisesRegex(pnsctl.OperatorError, "unresolved dispatch-bearing"):
                delivery._select_family_state(base, RESET)
            for path, data in original.items():
                self.assertEqual(path.read_bytes(), data)

    def test_recovery_does_not_adopt_an_older_pending_variant(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "flow"
            _historical_chip(base, pending=True)
            with self.assertRaises(pnsctl.OperatorError):
                delivery._select_family_state(base, RESET, recovery_variant="chip")
            with self.assertRaisesRegex(pnsctl.OperatorError, "unresolved dispatch-bearing"):
                delivery._select_family_state(base, RESET)

    def test_historical_metadata_is_never_current_completion_or_a_future_date(self):
        for day in ("local-2026-10-29-enhancement-gear", "local-2026-10-30-enhancement-gear",
                    "local-2026-02-31-enhancement-gear", "invalid-reset"):
            with self.subTest(day=day), tempfile.TemporaryDirectory() as folder:
                base = Path(folder) / "flow"
                _historical_chip(base, day)
                with self.assertRaisesRegex(pnsctl.OperatorError, "historical"):
                    delivery._select_family_state(base, RESET)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "flow"
            _historical_chip(base)
            self.assertEqual(delivery._select_family_state(base, RESET), (base / "occurrences" / RESET, RESET, {}))
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "flow"
            _historical_chip(base / "occurrences" / RESET)
            with self.assertRaises(pnsctl.OperatorError):
                delivery._select_family_state(base, RESET)

    def test_older_no_effect_uses_its_validated_reset_and_retains_claim_barrier(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            self._recover(base)
            progress = base / "family-progress.json"
            data = json.loads(progress.read_bytes())
            data["categories"]["gear"].pop("before_observation")
            progress.write_text(json.dumps(data), encoding="utf-8")
            tomorrow = "local-2026-10-30-enhancement-family"
            self.assertEqual(delivery._select_family_state(base, tomorrow), (base / "occurrences" / tomorrow, tomorrow, {}))
            delivery._claim_no_effect_continuation(base, "gear", invocation_id="one-attempt", session_directory=str(base / "claimed"))
            with self.assertRaisesRegex(pnsctl.OperatorError, "already claimed"):
                delivery._select_family_state(base, tomorrow)

    def test_actual_native_recovery_reaches_independent_wrapper_transition(self):
        from scripts import enhancement_bluestacks as native
        from scripts.bluestacks_native_runtime import captured_native_frame_from_png
        self.parser_patch.stop()
        fixture = Path(__file__).parent / "fixtures/enhancement_item_modal/native-gear-no-material-selected-20261029.png"
        payload = fixture.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            attempt, _receipt, _original, recovery = _state(root, payload)
            base = root / "flow"
            _historical_chip(base)
            current = base / "occurrences" / RESET
            current.mkdir(parents=True)
            self._pending(current, attempt)
            selected, selected_reset, completed = delivery._select_family_state(base, RESET, recovery_variant="gear")
            self.assertEqual((selected, selected_reset, completed), (current, RESET, {}))
            _rows(recovery / "events.jsonl", [])

            class Runtime:
                session = recovery
                input_count = 0
                ordinal = 0

                def capture(self, label):
                    self.ordinal += 1
                    ref, digest = _frame(recovery, f"native-{self.ordinal}-{label}", payload)
                    rows = _read_rows(recovery / "events.jsonl")
                    rows.append(_capture(ref, digest, 10 + self.ordinal, 20.0 + self.ordinal))
                    _rows(recovery / "events.jsonl", rows)
                    return captured_native_frame_from_png(
                        payload, path=recovery / ref, captured_monotonic=20.0 + self.ordinal,
                    )

            class Session:
                input_count = 0

                def observe(self, capture, *, label):
                    return capture(label)

            runtime = Runtime()
            with patch.object(native.time, "sleep"):
                route = native.run_recovery(runtime, variant="gear", reset_identity=RESET,
                    session=Session(), pending_attempt=delivery._pending_recovery_record(selected, "gear", RESET))
            self.assertEqual(route["status"], "recovered_no_effect", route)
            self.assertEqual(runtime.input_count, 0)
            self.assertEqual(runtime.ordinal, 2)
            self.assertFalse((recovery / "no-effect-recovery-receipt.json").exists())
            delivery._reconcile_recovery_no_effect(current, "gear", route, recovery_session=recovery)
            entry = json.loads((current / "family-progress.json").read_bytes())["categories"]["gear"]
            self.assertEqual(entry["status"], "confirmed_no_effect")
            self.assertFalse(route["semantic_successor_proven"])
            self.assertEqual(entry["original_attempt"]["before_observation"]["quantity"], 1)
            self.assertEqual(entry["no_effect_receipt"]["original_before_observation"]["quantity"], 0)
            self.assertEqual(delivery._select_family_state(base, RESET), (current, RESET, {}))


if __name__ == "__main__":
    unittest.main()
