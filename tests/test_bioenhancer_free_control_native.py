"""Native free Research control and paid/cooldown denial; no device access."""
import hashlib
import json
from pathlib import Path
import unittest

import cv2

from scripts import bioenhancer_free_research_route as bio


FIXTURE = Path(__file__).parent / "fixtures/bioenhancer_free_control/native-free-research-ready-20261031.png"


class BioenhancerFreeControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = FIXTURE.read_bytes()
        record = json.loads(FIXTURE.with_suffix(".json").read_text())
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise AssertionError("Native free-control source changed")
        cls.frame = cv2.imread(str(FIXTURE))

    def test_real_free_one_label_binds_only_inside_the_free_button(self):
        control = bio.bind_free_research(self.frame)
        self.assertIsNotNone(control)
        self.assertEqual(control.identity, "bioenhancer-free-research")
        x0, y0, x1, y1 = control.target_roi
        sx0, sy0, sx1, sy1 = bio.FREE_RESEARCH_SEED_ROI
        self.assertTrue(sx0 <= x0 < x1 <= sx1 and sy0 <= y0 < y1 <= sy1)
        self.assertEqual(control.evidence, ("ocr:free", "ocr:research", "ocr:1x"))

    def test_missing_free_or_quantity_cannot_borrow_paid_research(self):
        for box in ((180, 1143, 260, 1173), (264, 1175, 307, 1202), bio.FREE_RESEARCH_SEED_ROI):
            with self.subTest(erased=box):
                changed = self.frame.copy()
                x0, y0, x1, y1 = box
                changed[y0:y1, x0:x1] = 0
                self.assertIsNone(bio.bind_free_research(changed))

    def test_native_cooldown_never_binds_as_a_free_action(self):
        frame = cv2.imread(str(FIXTURE.parents[1] / "bioenhancer_exit/native-bio-research-cooldown.png"))
        self.assertIsNone(bio.bind_free_research(frame))
        self.assertIsNotNone(bio.recognize_free_research_cooldown(frame))


if __name__ == "__main__":
    unittest.main()
