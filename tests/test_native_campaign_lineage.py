"""Repeated battle frames require distinct, actually confirmed Stage parents."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime


ROI = (200, 300, 400, 500)
TARGETS = ("campaign-lineup-challenge", "campaign-auto", "campaign-victory-continue")


class MockTransport:
    def __init__(self):
        self.payload = b""
        self.inputs = []
        self.failure = None

    def capture_png(self):
        return self.payload

    def dispatch_tap(self, point):
        self.inputs.append(point)
        failure, self.failure = self.failure, None
        if failure is not None:
            raise failure


class NativeCampaignLineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pngs = {}
        for value in (20, 40, 60, 80, 100, 120, 140):
            valid, data = cv2.imencode(".png", np.full((1280, 800, 3), value, np.uint8))
            assert valid
            cls.pngs[value] = data.tobytes()

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.transport = MockTransport()
        self.runtime = LocalBlueStacksRuntime(self.transport, Path(directory.name), execute=True)
        delegated = patch("scripts.bluestacks_native_runtime.current_delegated_runtime_context", return_value=None)
        delegated.start()
        self.addCleanup(delegated.stop)

    def capture(self, value=40):
        self.transport.payload = self.pngs[value]
        return self.runtime.capture(f"source-{value}")

    def stage(self, key="entry-1", value=100, *, confirmed=True):
        self.runtime.tap(self.capture(value), target_identity="campaign-challenge-1-15-9",
                         target_roi=ROI, action_key=key, action_class="campaign_ap_challenge", consequential=True)
        post = self.capture()
        if confirmed:
            self.runtime.reconcile(key, "confirmed", post, "verified Hero Lineup")
        return post

    def child(self, target, parent, *, source=None, key=None, **changes):
        values = dict(target_identity=target, target_roi=ROI,
                      action_key=key or f"{parent}:{target}", consequential=target == TARGETS[0],
                      continuation_of=parent)
        values.update(changes)
        self.runtime.tap(source or self.capture({TARGETS[0]: 40, TARGETS[1]: 60, TARGETS[2]: 80}[target]), **values)

    def test_identical_lineup_auto_and_victory_repeat_only_under_new_confirmed_parents(self):
        for key, value in (("entry-1", 100), ("entry-2", 120)):
            self.stage(key, value)
            for target in TARGETS:
                self.child(target, key)
        self.assertEqual(len(self.transport.inputs), 8)
        self.assertEqual(self.runtime.input_count, 8)
        rows = [json.loads(line) for line in self.runtime.events.read_text().splitlines()]
        for target in TARGETS:
            child_rows = [row for row in rows if row["type"] == "dispatch" and row["target_identity"] == target]
            self.assertEqual([row["continuation_of"] for row in child_rows], ["entry-1", "entry-2"])
            self.assertEqual(child_rows[0]["source_sha256"], child_rows[1]["source_sha256"])
        # Scoped dispatches retain their global history for ordinary callers.
        with self.assertRaises(RuntimeError):
            self.child(TARGETS[1], None, key="unscoped-auto")
        self.assertEqual(len(self.transport.inputs), 8)

    def test_same_parent_cannot_repeat_a_child_even_with_different_pixels(self):
        self.stage()
        for target in TARGETS:
            self.child(target, "entry-1")
            before = len(self.transport.inputs)
            with self.assertRaises(RuntimeError):
                self.child(target, "entry-1", source=self.capture(140), key=f"retry:{target}")
            self.assertEqual(len(self.transport.inputs), before)

    def test_missing_unknown_and_unconfirmed_parent_cannot_authorize_lineup(self):
        post = self.stage(confirmed=False)
        self.runtime.reconcile("invented", "confirmed", post, "unknown key grants no lineage")
        for parent in (None, "", "invented", "entry-1"):
            with self.subTest(parent=parent), self.assertRaises(RuntimeError):
                self.child(TARGETS[0], parent, key=f"blocked:{parent}")
        self.assertEqual(len(self.transport.inputs), 1)

    def test_confirmed_parent_must_bind_its_actual_lineup_successor_hash(self):
        self.stage()
        with self.assertRaises(RuntimeError):
            self.child(TARGETS[0], "entry-1", source=self.capture(140))
        self.assertEqual(len(self.transport.inputs), 1)

    def test_failed_stage_transport_cannot_be_promoted_by_later_confirmed_reconciliation(self):
        self.transport.failure = RuntimeError("ambiguous transport")
        with self.assertRaises(RuntimeError):
            self.stage()
        post = self.capture()
        with self.assertRaises(RuntimeError):
            self.runtime.reconcile("entry-1", "confirmed", post, "cannot repair transport ambiguity")
        with self.assertRaises(RuntimeError):
            self.child(TARGETS[0], "entry-1")
        self.assertEqual(len(self.transport.inputs), 1)
        self.assertEqual(self.runtime.input_count, 1)

    def test_failed_or_unresolved_parent_stays_closed_after_reconfirmation_attempt(self):
        for index, status in enumerate(("failed_confirmed", "unresolved")):
            key = f"entry-{index}"
            post = self.stage(key, (100, 120)[index])
            self.runtime.reconcile(key, status, post, "parent is no longer confirmed")
            with self.assertRaises(RuntimeError):
                self.runtime.reconcile(key, "confirmed", post, "cannot rearm invalidated parent")
            with self.assertRaises(RuntimeError):
                self.child(TARGETS[0], key)
        self.assertEqual(len(self.transport.inputs), 2)

    def test_auto_and_continue_require_successful_lineup_transport(self):
        self.stage()
        for target in TARGETS[1:]:
            with self.assertRaises(RuntimeError):
                self.child(target, "entry-1")
        self.transport.failure = RuntimeError("Lineup input uncertain")
        with self.assertRaises(RuntimeError):
            self.child(TARGETS[0], "entry-1")
        self.runtime.reconcile("entry-1:campaign-lineup-challenge", "confirmed", self.capture(60),
                               "a child reconciliation cannot rearm its parent")
        for target in TARGETS:
            with self.assertRaises(RuntimeError):
                self.child(target, "entry-1", key=f"after-failure:{target}")
        self.assertEqual(len(self.transport.inputs), 2)

    def test_wrong_child_class_or_consequence_never_uses_lineage_exception(self):
        self.stage()
        for target in TARGETS:
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                self.child(target, "entry-1", action_class="combat_confirmation")
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                self.child(target, "entry-1", consequential=target != TARGETS[0])
        self.assertEqual(len(self.transport.inputs), 1)

    def test_ordinary_duplicates_and_unscoped_victory_recovery_keep_global_guard(self):
        source = self.capture()
        self.runtime.tap(source, target_identity="ordinary-navigation", target_roi=ROI,
                         action_key="first", continuation_of="arbitrary")
        with self.assertRaises(RuntimeError):
            self.runtime.tap(self.capture(), target_identity="ordinary-navigation", target_roi=ROI,
                             action_key="second", continuation_of="another-parent")
        self.child(TARGETS[2], None, key="victory-only-recovery")
        with self.assertRaises(RuntimeError):
            self.child(TARGETS[2], None, key="victory-only-repeat")
        self.assertEqual(len(self.transport.inputs), 2)


if __name__ == "__main__":
    unittest.main()
