"""Current native Scarlett context must remain complete before safe Back binds."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import pytesseract

from scripts import startup_surface_recognition as surfaces


FIXTURE = Path(__file__).parent / "fixtures/startup/scarlett-current-20261030.png"


class ScarlettCurrentContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = FIXTURE.read_bytes()
        cls.frame = cv2.imdecode(np.frombuffer(cls.raw, np.uint8), cv2.IMREAD_COLOR)
        original = pytesseract.image_to_string
        cache = {}
        def ocr(image, **kwargs):
            key = image.shape, hashlib.sha256(image.tobytes()).hexdigest(), kwargs.get("config")
            if key not in cache:
                cache[key] = original(image, **kwargs)
            return cache[key]
        cls.patcher = patch.object(pytesseract, "image_to_string", side_effect=ocr)
        cls.patcher.start()
        cls.addClassCleanup(cls.patcher.stop)

    def recognize(self, frame):
        ok, encoded = cv2.imencode(".png", frame)
        self.assertTrue(ok)
        return surfaces.recognize_scarlett_three_day_pack(frame, encoded.tobytes())

    def test_actual_current_context_binds_only_measured_safe_back(self):
        provenance = json.loads(FIXTURE.with_suffix(".provenance.json").read_text())
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), provenance["sha256"])
        result = surfaces.recognize_scarlett_three_day_pack(self.frame, self.raw)
        self.assertTrue(result["recognized"], result)
        self.assertTrue(surfaces.is_exact_scarlett_recognition(result))
        self.assertEqual(result["measured_back_roi"], (47, 0, 128, 59))
        self.assertEqual(result["safe_exit_roi"], surfaces.SCARLETT_SAFE_BACK_ROI)
        self.assertEqual(result["target_count"], 1)
        self.assertTrue(result["purchase_exclusion_verified"])
        self.assertEqual(result["max_inputs"], 1)

    def test_each_required_context_region_remains_necessary(self):
        for name, roi in (("max", (50, 265, 300, 327)), ("build", (50, 328, 750, 395)),
                ("free_speedup", (50, 395, 750, 465)), ("days", surfaces.SCARLETT_DAYS_ROI),
                ("notice", surfaces.SCARLETT_NOTICE_ROI)):
            with self.subTest(region=name):
                frame = self.frame.copy()
                x0, y0, x1, y1 = roi
                frame[y0:y1, x0:x1] = 0
                self.assertFalse(self.recognize(frame)["recognized"])

    def test_title_and_visible_back_remain_required(self):
        for roi in (surfaces.SCARLETT_TITLE_ROI, (0, 0, 180, 90)):
            frame = self.frame.copy()
            x0, y0, x1, y1 = roi
            frame[y0:y1, x0:x1] = 0
            self.assertFalse(self.recognize(frame)["recognized"])

    def test_confirmation_overlay_blocks_even_with_all_offer_text_present(self):
        frame = self.frame.copy()
        cv2.rectangle(frame, (180, 710), (640, 900), (30, 30, 30), -1)
        cv2.putText(frame, "Confirm", (240, 780), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
        cv2.putText(frame, "Cancel", (260, 855), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
        self.assertFalse(self.recognize(frame)["recognized"])

    def test_cross_frame_bytes_and_ambiguous_exit_still_fail_closed(self):
        result = surfaces.recognize_scarlett_three_day_pack(self.frame, b"different frame")
        self.assertFalse(result["recognized"])
        candidate = {"target_identity": surfaces.SCARLETT_SAFE_BACK_TARGET_IDENTITY,
            "roi": surfaces.SCARLETT_SAFE_BACK_ROI}
        result = surfaces.recognize_scarlett_three_day_pack(self.frame, self.raw,
            target_candidates=[candidate, candidate])
        self.assertFalse(result["recognized"])


if __name__ == "__main__":
    unittest.main()
