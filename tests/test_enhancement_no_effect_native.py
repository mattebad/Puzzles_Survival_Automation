"""Actual zero-selected PNGs support only bounded observe-only NoEffect proof."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png


FRAME = Path(__file__).parent / "fixtures/enhancement_item_modal/native-gear-no-material-selected-20261029.png"


class NativeNoEffectTests(unittest.TestCase):
    def setup_attempt(self, root):
        raw = FRAME.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        original = root / "original"
        original.mkdir()
        source, post = original / "before.png", original / "post.png"
        source.write_bytes(raw)
        post.write_bytes(raw)
        key = "enhancement:gear:enhancement-use:original"
        rows = [{"type": "capture", "path": str(source), "sha256": digest, "captured_monotonic": 1.},
            {"type": "dispatch", "action_key": key, "target_identity": "enhancement-use", "execute": True, "source_sha256": digest},
            {"type": "capture", "path": str(post), "sha256": digest, "captured_monotonic": 2.}]
        (original / "events.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n")
        pending = {"variant": "gear", "status": "dispatch_bearing_unresolved", "runtime_session": str(original),
            "resource_affecting_action_key": key, "source_frame_sha256": digest, "resource_affecting_dispatch_count": 1,
            "before_observation": {"quantity": 1, "game_day_id": "current-reset", "source_frame_sha256": digest,
                                   "evidence_refs": [str(source)]}}
        class Runtime:
            input_count = 0
            def __init__(self):
                self.session = root / "recovery"
                self.session.mkdir()
                self.ordinal = 0
            def capture(self, label):
                self.ordinal += 1
                path = self.session / f"{self.ordinal}-{label}.png"
                path.write_bytes(raw)
                return captured_native_frame_from_png(raw, path=path, captured_monotonic=10. + self.ordinal)
            def tap(self, *args, **kwargs):
                raise AssertionError("NoEffect proof cannot dispatch")
        class Session:
            input_count = 0
            def observe(self, capture, *, label):
                return capture(label)
        return Runtime(), Session(), pending, post

    def test_four_actual_zero_selected_frames_report_no_effect_without_rewriting_old_quantity(self):
        with tempfile.TemporaryDirectory(dir=".local-orchestrator") as folder:
            runtime, session, pending, _ = self.setup_attempt(Path(folder).absolute())
            before = json.loads(json.dumps(pending))
            with patch.object(native.time, "sleep"):
                result = native.run_recovery(runtime, variant="gear", reset_identity="current-reset", session=session, pending_attempt=pending)
            self.assertEqual(result["status"], "recovered_no_effect", result)
            self.assertEqual(pending, before)
            self.assertEqual(pending["before_observation"]["quantity"], 1)
            self.assertEqual(runtime.ordinal, 2)
            receipt = result["no_effect_receipt"]
            for name in ("original_before_observation", "original_immediate_post_observation", "immediate_recovery_observation", "later_recovery_observation"):
                item = receipt[name]
                self.assertEqual((item["quantity"], item["material_inventory_count"], item["item_exp_current"]), (0, 9562, 10))
                self.assertEqual(item["material_slot_facts"], ((0, 4, 0, 2), (1, 1, 0, 9562), (2, 0, 0, 100)))
                self.assertFalse(item["item_equipped"])
            self.assertFalse(receipt["input_authority"])
            self.assertTrue(receipt["read_only"])
            self.assertEqual((result["input_count"], result["dispatch_count"], result["resource_affecting_dispatch_count"]), (0, 0, 0))
            self.assertFalse((runtime.session / "no-effect-recovery-receipt.json").exists())

    def test_changed_original_or_wrong_reset_never_produces_no_effect_proof(self):
        for defect in ("bytes", "reset"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory(dir=".local-orchestrator") as folder:
                runtime, session, pending, post = self.setup_attempt(Path(folder).absolute())
                if defect == "bytes":
                    post.write_bytes(b"changed")
                else:
                    pending["before_observation"]["game_day_id"] = "another-reset"
                with patch.object(native.time, "sleep"):
                    result = native.run_recovery(runtime, variant="gear", reset_identity="current-reset", session=session, pending_attempt=pending)
                self.assertEqual(result["status"], "evidence_required", result)
                self.assertNotIn("no_effect_receipt", result)

    def test_navigation_mode_cannot_be_combined_with_effect_recovery(self):
        with self.assertRaises(ValueError):
            native.run_recovery(None, variant="gear", reset_identity="current-reset", session=None,
                pending_attempt={}, navigation_only=True)


if __name__ == "__main__":
    unittest.main()
