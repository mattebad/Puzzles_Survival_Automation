"""Offline source-bound positive Enhancement recovery proof tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts import flow_delivery_enhancement_bluestacks as delivery
from scripts import pnsctl
from tasks.runtime_identity import BLUESTACKS_SERIAL
from tests.support.enhancement_replay import CategoryResumeCase


class PositiveRecoveryDeliveryTests(unittest.TestCase):
    def setUp(self):
        helper = CategoryResumeCase()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        self.case = helper.make_session(("gear",))
        self.reset = self.case.reset
        proof = self.case.result["enhancement_result"]["category_results"][0]
        self.successor = copy.deepcopy(proof["successor_observation"])
        proof.update(status="dispatch_bearing_unresolved", successor_observation=None)
        helper.persist(self.case)
        self.original = copy.deepcopy(proof)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.recovery = self.root / "recovery"
        (self.recovery / "frames").mkdir(parents=True)
        rows, observations = [], []
        png = Path(self.successor["evidence_refs"][0]).read_bytes()
        for index, clock in enumerate((100, 102)):
            path = self.recovery / "frames" / f"{index + 1:04d}.png"
            path.write_bytes(png)
            obs = dict(self.successor, evidence_refs=[str(path)])
            observations.append(obs)
            rows.append({"type": "capture", "path": str(path), "sha256": hashlib.sha256(png).hexdigest(),
                         "captured_monotonic": clock, "timestamp": self.case.timestamp(clock)})
        self.rows = rows
        self.receipt = {"proof_kind": "settled_successor", "read_only": True, "input_authority": False,
            "original_action_key": proof["resource_affecting_action_key"],
            "original_runtime_session": str(self.case.session), "reset_identity": self.reset,
            "original_delivery_sha256": hashlib.sha256((self.case.session / "flow-delivery-result.json").read_bytes()).hexdigest(),
            "original_source_frame_sha256": proof["source_frame_sha256"],
            "successor_observation": self.successor, "successor_evidence_ref": self.successor["evidence_refs"][0],
            "recovery_session_directory": str(self.recovery),
            "immediate_recovery_observation": observations[0], "later_recovery_observation": observations[1],
            "input_count": 0, "dispatch_count": 0, "resource_affecting_dispatch_count": 0}
        self.route = {"status": "recovered_successor", "successor_receipt": self.receipt,
            "successor_observation": self.successor, "successor_evidence_ref": self.receipt["successor_evidence_ref"],
            "semantic_successor_proven": True, "terminal_recognized": False, "recovery_only": True,
            "proof_kind": "settled_successor", "read_only": True, "input_authority": False, "dispatch": False,
            "input_count": 0, "dispatch_count": 0, "resource_affecting_dispatch_count": 0}
        self.recovery_delivery = {"flow_id": delivery.FLOW_ID, "variant": "family", "status": "recovered_successor",
            "serial": BLUESTACKS_SERIAL, "native_width": 800, "native_height": 1280,
            "production_registration": "NOT_REGISTERED", "scheduler_enabled": False,
            "frames": [str(Path(row["path"]).relative_to(self.recovery)) for row in rows],
            "events_path": "events.jsonl", "input_count": 0, "dispatch_count": 0,
            "resource_affecting_dispatch_count": 0, "enhancement_result": self.route}
        self.persist_recovery()
        self.progress = self.root / "family-progress.json"
        self.progress.write_text(json.dumps({"schema_version": 1, "flow_id": delivery.FLOW_ID,
                                             "categories": {"gear": self.original}}))
        self.selection = patch("scripts.enhancement_bluestacks.recognize_selection_context", self.case.selection)
        self.commander = patch("scripts.enhancement_bluestacks.recognize_commander_stage", self.case.commander)
        self.selection.start(); self.commander.start()
        self.addCleanup(self.selection.stop); self.addCleanup(self.commander.stop)

    def persist_recovery(self):
        (self.recovery / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.rows))
        (self.recovery / "flow-delivery-result.json").write_text(json.dumps(self.recovery_delivery))

    def validate(self):
        delivery._validate_positive_receipt(self.original, "gear", self.reset, self.receipt)

    def test_replay_and_receipt_before_progress_preserve_original(self):
        before = (self.case.session / "flow-delivery-result.json").read_bytes()
        self.validate()
        delivery._reconcile_recovery_successor(self.root, "gear", self.route)
        value = json.loads(self.progress.read_text())["categories"]["gear"]
        self.assertEqual(value["status"], "completed")
        self.assertEqual(value["resource_affecting_action_key"], self.original["resource_affecting_action_key"])
        self.assertTrue(Path(value["successor_receipt_path"]).is_file())
        self.assertEqual((self.case.session / "flow-delivery-result.json").read_bytes(), before)
        delivery._read_positive_receipt(value, "gear", self.reset)
        loaded = delivery._load_family_progress(self.root, reset_identity=self.reset)
        self.assertEqual(loaded["gear"]["status"], "completed")
        self.assertEqual(delivery._verify_retained_categories({"gear": value}, self.reset)["gear"]["status"], "verified")
        verified = delivery.verify_enhancement_family({"result": self.recovery_delivery,
            "session_directory": str(self.recovery), "frames": self.recovery_delivery["frames"]}, {}, {})
        self.assertTrue(verified["successor_recovered"])
        self.assertFalse(verified["family_completed"])
        self.assertEqual((verified["input_count"], verified["dispatch_count"]), (0, 0))

    def test_legacy_reconciled_proof_only_accounts_for_prior_occurrence(self):
        delivery._reconcile_recovery_successor(self.root, "gear", self.route)
        progress = json.loads(self.progress.read_text())
        value = progress["categories"]["gear"]
        del value["successor_receipt_path"]
        del value["successor_receipt_sha256"]
        self.progress.write_text(json.dumps(progress))
        next_reset = "local-2026-10-30-enhancement-family"
        self.assertEqual(delivery._historical_family_accounting(self.root, next_reset, None), {"gear"})
        _current_root, selected_reset, completed = delivery._select_family_state(self.root, next_reset)
        self.assertEqual(selected_reset, next_reset)
        self.assertEqual(completed, {})
        with self.assertRaises(Exception):
            delivery._load_family_progress(self.root, reset_identity=self.reset)
        for key in ("successor_receipt_path", "successor_receipt_sha256"):
            with self.subTest(key=key):
                value[key] = "malformed"
                self.progress.write_text(json.dumps(progress))
                with self.assertRaises(Exception):
                    delivery._historical_family_accounting(self.root, next_reset, None)
                del value[key]

    def test_identity_reset_and_original_hash_mismatch_fail_without_progress_change(self):
        original = self.progress.read_bytes()
        for key, wrong in (("reset_identity", "local-2099-01-01-enhancement-family"),
                           ("original_action_key", "enhancement:gear:wrong"),
                           ("original_delivery_sha256", "0" * 64)):
            with self.subTest(key=key):
                self.receipt[key], saved = wrong, self.receipt[key]
                with self.assertRaises(Exception):
                    delivery._reconcile_recovery_successor(self.root, "gear", self.route)
                self.receipt[key] = saved
        self.assertEqual(self.progress.read_bytes(), original)
        self.assertFalse((self.recovery / delivery._POSITIVE_RECEIPT_NAME).exists())

    def test_duplicate_and_intervening_recovery_input_fail_closed(self):
        original = self.progress.read_bytes()
        self.rows.append({"type": "dispatch", "action_key": "unexpected"})
        self.persist_recovery()
        with self.assertRaises(Exception):
            delivery._reconcile_recovery_successor(self.root, "gear", self.route)
        self.assertEqual(self.progress.read_bytes(), original)
        self.rows.pop(); self.rows.append(dict(self.rows[0])); self.persist_recovery()
        with self.assertRaises(Exception):
            delivery._reconcile_recovery_successor(self.root, "gear", self.route)
        self.assertEqual(self.progress.read_bytes(), original)

    def test_pending_wrapper_denies_child_inputs_despite_outer_budget(self):
        outer = SimpleNamespace(owner="automation-service:enhancement", session_directory=self.root / "outer")
        outer.session_directory.mkdir()
        child = SimpleNamespace(session=self.root / "native", max_inputs=1, checkpoint=None)
        child.session.mkdir()
        def stop_after_scope(runtime, **kwargs):
            self.assertEqual(runtime.max_inputs, 0)
            self.assertIs(kwargs["pending_attempt"], self.original)
            raise RuntimeError("offline scope checked")
        with patch.object(delivery, "_outer_session", return_value=outer), \
                patch.object(delivery, "_initial_observation", return_value={}), \
                patch.object(delivery, "_select_family_state", return_value=(self.root, self.reset, {})), \
                patch.object(delivery, "_read_family_progress_categories", return_value=(self.progress, {"gear": self.original})), \
                patch.object(delivery.LocalBlueStacksRuntime, "connect", return_value=child), \
                patch("scripts.enhancement_bluestacks.run_recovery", side_effect=stop_after_scope):
            with self.assertRaisesRegex(RuntimeError, "offline scope checked"):
                delivery.run_enhancement_family({}, {"enhancement_variant": "gear", "max_inputs": 1,
                    "enhancement_recovery_only": True, "enhancement_reset_identity": self.reset,
                    "checkpoint": lambda: None}, live=True)

    def test_fresh_png_tamper_and_wrong_successor_reject(self):
        original = self.progress.read_bytes()
        later = Path(self.receipt["later_recovery_observation"]["evidence_refs"][0])
        later.write_bytes(b"not a PNG")
        with self.assertRaises(Exception):
            self.validate()
        self.assertEqual(self.progress.read_bytes(), original)

    def test_receipt_written_before_progress_and_failure_cannot_mark_complete(self):
        original = self.progress.read_bytes()
        with patch.object(delivery, "_read_positive_receipt", side_effect=ValueError("replay failed")):
            with self.assertRaises(ValueError):
                delivery._reconcile_recovery_successor(self.root, "gear", self.route)
        self.assertTrue((self.recovery / delivery._POSITIVE_RECEIPT_NAME).is_file())
        self.assertEqual(self.progress.read_bytes(), original)

    def test_receipt_collision_and_lease_loss_never_complete_progress(self):
        path = self.recovery / delivery._POSITIVE_RECEIPT_NAME
        path.write_text("existing")
        original = self.progress.read_bytes()
        with self.assertRaises(FileExistsError):
            delivery._reconcile_recovery_successor(self.root, "gear", self.route)
        self.assertEqual(self.progress.read_bytes(), original)
        path.unlink()
        def stop():
            raise RuntimeError("lease lost")
        with self.assertRaises(Exception):
            delivery._reconcile_recovery_successor(self.root, "gear", self.route, checkpoint=stop)
        self.assertEqual(self.progress.read_bytes(), original)
