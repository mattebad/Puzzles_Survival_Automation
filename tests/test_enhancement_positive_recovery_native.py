"""An original settled Gear successor can be reconciled with zero new inputs."""
from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png


FIXTURES = Path(__file__).parent / "fixtures/enhancement_material_label_crop"


class PositiveRecoveryNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.stack.enter_context(patch.object(native.time, "sleep"))
        original_ocr, original_label = native._default_ocr, native._material_label
        ocr_cache, label_cache = {}, {}
        def ocr(frame, roi):
            x0, y0, x1, y1 = roi
            key = roi, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
            if key not in ocr_cache:
                ocr_cache[key] = original_ocr(frame, roi)
            return list(ocr_cache[key])
        def label(frame, box):
            x0, y0, x1, y1 = box
            key = box, hashlib.sha256(frame[y0:y1, x0:x1].tobytes()).hexdigest()
            if key not in label_cache:
                label_cache[key] = original_label(frame, box)
            return label_cache[key]
        cls.stack.enter_context(patch.object(native, "_default_ocr", side_effect=ocr))
        cls.stack.enter_context(patch.object(native, "_material_label", side_effect=label))
        cls.names = list(json.loads((FIXTURES / "provenance.json").read_text())["frames"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.original = self.root / "original"
        self.original.mkdir()
        captures = []
        self.rows = []
        for index, name in enumerate(self.names, 1):
            path = self.original / name
            path.write_bytes((FIXTURES / name).read_bytes())
            capture = captured_native_frame_from_png(path.read_bytes(), path=path, captured_monotonic=float(index))
            captures.append(capture)
        modal, baseline, quantity, source, successor = captures
        before = native.recognize_selection_context(source, modal=modal, baseline=baseline,
            quantity=quantity, variant="gear", game_day_id="current-reset")
        self.assertTrue(before.recognized, before)
        self.key = "enhancement:gear:enhancement-use:original"
        def capture_row(capture):
            return {"type": "capture", "path": str(capture.path), "sha256": capture.sha256,
                "captured_monotonic": capture.captured_monotonic}
        for frame, identity, target in ((modal, "open-enhance:gear", "modal_enhance"),
                (baseline, "material-select:gear", "baseline_card"), (quantity, "quantity-use", "quantity_use")):
            self.rows.extend((capture_row(frame), {"type": "dispatch", "target_identity": identity,
                "execute": True, "source_sha256": frame.sha256,
                "target_roi": before.diagnostics["selection_context_targets"][target]}))
        self.rows.extend((capture_row(source), {"type": "dispatch", "target_identity": "enhancement-use",
            "action_key": self.key, "execute": True, "source_sha256": source.sha256,
            "target_roi": before.observation.target_roi}, {"type": "dispatch_classification",
            "action_key": self.key, "resource_affecting": True, "action_class": "resource_affecting_confirmation"},
            capture_row(successor)))
        self.pending = json.loads(json.dumps({"variant": "gear", "status": "dispatch_bearing_unresolved",
            "resource_affecting_dispatch_count": 1, "runtime_session": str(self.original),
            "resource_affecting_action_key": self.key, "source_frame_sha256": source.sha256,
            "before_observation": asdict(before.observation)}))
        self.write_original()
        owner = self
        class Runtime:
            input_count = 0
            def __init__(self):
                self.session = owner.root / "recovery"
                self.session.mkdir()
                self.events = self.session / "events.jsonl"
                self.ordinal = 0
                self.raw = successor.png
            def capture(self, label):
                self.ordinal += 1
                path = self.session / f"{self.ordinal}-{label}.png"
                path.write_bytes(self.raw)
                frame = captured_native_frame_from_png(self.raw, path=path, captured_monotonic=10. + self.ordinal)
                with self.events.open("a") as handle:
                    handle.write(json.dumps(capture_row(frame)) + "\n")
                return frame
            def tap(self, *args, **kwargs):
                raise AssertionError("positive successor proof cannot dispatch")
        class Session:
            input_count = 0
            def observe(self, capture, *, label):
                return capture(label)
        self.runtime, self.session = Runtime(), Session()
        self.baseline_raw = baseline.png

    def write_original(self):
        (self.original / "events.jsonl").write_text("\n".join(map(json.dumps, self.rows)) + "\n")
        (self.original / "flow-delivery-result.json").write_text(json.dumps(
            {"enhancement_result": {"category_results": [self.pending]}}))

    def recover(self):
        return native.run_recovery(self.runtime, variant="gear", reset_identity="current-reset",
            session=self.session, pending_attempt=self.pending)

    def test_original_positive_and_two_current_frames_prove_effect_without_new_confirm(self):
        original_bytes = (self.original / "flow-delivery-result.json").read_bytes()
        result = self.recover()
        self.assertEqual(result["status"], "recovered_successor", result)
        receipt = result["successor_receipt"]
        self.assertEqual(receipt["original_delivery_sha256"], hashlib.sha256(original_bytes).hexdigest())
        self.assertEqual(Path(receipt["successor_evidence_ref"]).parent, self.original)
        self.assertEqual(result["successor_observation"]["material_inventory_count"], 9560)
        self.assertEqual(result["successor_observation"]["item_exp_current"], 30)
        self.assertEqual(self.runtime.ordinal, 2)
        self.assertEqual((result["input_count"], result["dispatch_count"], result["resource_affecting_dispatch_count"]), (0, 0, 0))
        self.assertTrue(result["semantic_successor_proven"])
        self.assertFalse(result["terminal_recognized"])
        self.assertFalse(receipt["input_authority"])
        self.assertTrue(receipt["read_only"])
        self.assertEqual((self.original / "flow-delivery-result.json").read_bytes(), original_bytes)

    def test_positive_receipt_matches_persisted_delivery_without_container_type_drift(self):
        result = self.recover()
        self.assertEqual(result["status"], "recovered_successor", result)
        delivery = self.runtime.session / "recovery-delivery.json"
        delivery.write_text(json.dumps(result))
        recovered = json.loads(delivery.read_text())
        self.assertEqual(recovered["successor_receipt"], result["successor_receipt"])
        self.assertEqual(recovered["successor_observation"], result["successor_observation"])
        self.assertEqual(recovered["successor_receipt"]["successor_observation"],
            recovered["successor_observation"])

    def test_wrong_reset_rejects(self):
        self.pending["before_observation"]["game_day_id"] = "other-reset"
        self.write_original()
        self.assertEqual(self.recover()["status"], "evidence_required")

    def test_changed_original_png_rejects(self):
        (self.original / self.names[-1]).write_bytes(b"changed")
        self.assertEqual(self.recover()["status"], "evidence_required")

    def test_intervening_input_blocks_adoption_of_later_original_successor(self):
        self.rows.insert(-1, {"type": "dispatch", "target_identity": "another-control"})
        self.write_original()
        self.assertEqual(self.recover()["status"], "evidence_required")

    def test_nonzero_recovery_input_rejects(self):
        self.runtime.input_count = 1
        self.assertEqual(self.recover()["status"], "evidence_required")

    def test_input_during_second_capture_rejects(self):
        original = self.runtime.capture
        def capture(label):
            frame = original(label)
            if self.runtime.ordinal == 2:
                self.runtime.input_count = 1
            return frame
        self.runtime.capture = capture
        self.assertEqual(self.recover()["status"], "evidence_required")

    def test_duplicate_confirm_rejects(self):
        self.rows.insert(-1, dict(self.rows[7]))
        self.write_original()
        self.assertEqual(self.recover()["status"], "evidence_required")

    def test_no_retained_positive_cannot_be_replaced_by_current_positive(self):
        self.rows = self.rows[:-1]
        self.write_original()
        self.assertEqual(self.recover()["status"], "evidence_required")

    def test_current_unchanged_stock_and_exp_do_not_prove_consumption(self):
        self.runtime.raw = self.baseline_raw
        self.assertEqual(self.recover()["status"], "evidence_required")

    def test_wrong_current_identity_or_committed_exp_rejects(self):
        original = native.recognize_commander_stage
        for field, value in (("selected_item_identity", "another suit"), ("item_exp_current", 31)):
            def changed(frame, **kwargs):
                result = original(frame, **kwargs)
                if Path(kwargs.get("evidence_ref", "")).parent == self.runtime.session and result.observation:
                    return replace(result, observation=replace(result.observation, **{field: value}))
                return result
            with self.subTest(field=field), patch.object(native, "recognize_commander_stage", side_effect=changed):
                self.assertEqual(self.recover()["status"], "evidence_required")


if __name__ == "__main__":
    unittest.main()
