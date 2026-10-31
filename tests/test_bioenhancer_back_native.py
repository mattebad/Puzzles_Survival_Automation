"""Bioenhancer Research exits through its measured, unobscured native arrow."""

import hashlib
import json
from pathlib import Path
import unittest

import cv2

from scripts import bioenhancer_free_research_canary as bio
from tasks.home_atlas_vision import frame_digest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/bioenhancer_exit"


class BioenhancerBackNativeTests(unittest.TestCase):
    @staticmethod
    def frame():
        return cv2.imread(str(FIXTURES / "native-bio-research-cooldown.png"))

    def test_native_research_title_arrow_and_animation_variance(self):
        frame = self.frame()
        control = bio.bind_bioenhancer_back(frame)
        self.assertIsNotNone(control)
        self.assertEqual(control.target_roi, (47, 2, 128, 61))
        variant = frame.copy()
        variant[80:] = cv2.convertScaleAbs(variant[80:], alpha=0.85, beta=6)
        self.assertNotEqual(frame_digest(frame), frame_digest(variant))
        self.assertEqual(bio.bind_bioenhancer_back(variant).target_roi, control.target_roi)

    def test_wrong_or_obscured_header_and_missing_arrow_fail_closed(self):
        for label in ("wrong_title", "obscured_header", "missing_arrow"):
            with self.subTest(case=label):
                frame = self.frame()
                if label == "missing_arrow":
                    frame[:90, :180] = 0
                else:
                    frame[:80, 140:700] = 0
                    if label == "wrong_title":
                        cv2.putText(frame, "Bioenhancer Settings", (200, 50), cv2.FONT_HERSHEY_SIMPLEX,
                                    1.1, (255, 255, 255), 2, cv2.LINE_AA)
                self.assertIsNone(bio.bind_bioenhancer_back(frame))

    def test_real_retained_vip_and_independent_unknown_panel_fail_closed(self):
        vip = cv2.imread(str(ROOT / "tasks/assets/navigation/800x1280/reset_popup_source.png"))
        frame = self.frame()
        frame[320:900, 40:760] = vip[320:900, 40:760]
        self.assertIsNone(bio.bind_bioenhancer_back(frame))
        for left, top, right, bottom in ((170, 420, 630, 860), (60, 370, 740, 920)):
            with self.subTest(panel=(left, top, right, bottom)):
                frame = self.frame()
                cv2.rectangle(frame, (left, top), (right, bottom), (35, 35, 35), -1)
                cv2.rectangle(frame, (left, top), (right, bottom), (220, 220, 220), 5)
                cv2.putText(frame, "Unexpected", (left + 40, top + 80), cv2.FONT_HERSHEY_SIMPLEX,
                            1.1, (255, 255, 255), 2, cv2.LINE_AA)
                self.assertIsNone(bio.bind_bioenhancer_back(frame))

    def test_native_fixture_integrity(self):
        provenance = json.loads((FIXTURES / "provenance.json").read_text())
        payload = (FIXTURES / provenance["fixture"]).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), provenance["transport_sha256"])
        self.assertEqual(self.frame().shape, (1280, 800, 3))
