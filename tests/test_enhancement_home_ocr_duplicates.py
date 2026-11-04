"""One physical profile badge may have multiple OCR boxes; ambiguity still stops."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png
from tests.support.environment import requires_tesseract


FRAME = Path(__file__).parent / "fixtures/enhancement_item_modal/native-home-duplicate-level-20261029.png"
# Exact zero-input pass5 source:
# .local-captures/automation-service-authorized/soak-20261029T154450634914Z-81e47e7e/
# enhancement/enhancement-20261029T154450654734Z-7b94b167/runtime/
# enhancement-family-20261029T154516958540Z/frames/0001-family-startup.png
SHA = "d53b42e8fcb6f0e26a6616d2310bcfba13976a4f05d931f255fe479fe29a092d"
TIGHT = native.OcrHit("47", (13, 66, 36, 81), 96.)
WIDE = native.OcrHit("47", (2, 54, 38, 97), 68.)
VIP = native.OcrHit("VIP10", (133, 68, 213, 90), 73.)


class HomeDuplicateOcrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = FRAME.read_bytes()
        cls.frame = cv2.imdecode(np.frombuffer(cls.raw, np.uint8), cv2.IMREAD_COLOR)

    @requires_tesseract
    def test_actual_default_ocr_nested_badge_is_admitted_from_native_source(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), SHA)
        actual = native._default_ocr(self.frame, native.HOME_PROFILE_SEARCH_ROI)
        # Engine builds differ on the wide reading of this badge: the capture
        # machine read "47" at WIDE.bounds; tesseract 5.3.0 (Linux CI) and
        # 5.5.4 (macOS) read "47S" at (2, 54, 91, 97). The premise is the same
        # on every build: the tight badge, plus exactly one wider "47..."
        # reading that encloses it, and no "47" reading anywhere else.
        def encloses(hit):
            x0, y0, x1, y1 = hit.bounds
            tx0, ty0, tx1, ty1 = TIGHT.bounds
            return x0 <= tx0 and y0 <= ty0 and tx1 <= x1 and ty1 <= y1
        badges = [hit for hit in actual if native._normalize(hit.text) == "47"]
        self.assertIn(TIGHT.bounds, {hit.bounds for hit in badges})
        self.assertTrue(all(encloses(hit) for hit in badges), badges)
        wider = [hit for hit in actual if native._normalize(hit.text).startswith("47")
                 and hit.bounds != TIGHT.bounds and encloses(hit)]
        self.assertEqual(len(wider), 1, actual)
        result = native.recognize_home_frame(self.frame, source_frame_sha256=SHA)
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.frame_sha256, SHA)
        self.assertEqual(result.portrait_identity, "profile-level-47")
        self.assertEqual(result.portrait_target, native.HOME_PROFILE_PORTRAIT_ROI)

    def test_same_glyph_uses_higher_confidence_then_tighter_source_measurement(self):
        for wide_confidence in (68., 96.):
            hits = [native.OcrHit(" 47 ", WIDE.bounds, wide_confidence), TIGHT, VIP]
            # Scene recognition is independent of the synthetic profile OCR cases.
            with (
                patch.object(native, "is_clean_home_frame", return_value=True),
                patch.object(native, "_profile_portrait_visual_present", return_value=False),
            ):
                result = native.recognize_home_frame(self.frame, ocr_engine=lambda *_: hits)
            self.assertTrue(result.recognized, result)
            self.assertEqual(result.portrait_target, (0, 41, 61, 106))

    def dispatch(self, hits):
        test = self
        class Runtime:
            def __init__(self):
                self.inputs = []
                self.ordinal = 0
            def capture(self, label):
                self.ordinal += 1
                return captured_native_frame_from_png(test.raw, path=Path(f"unit-home-{self.ordinal}.png"), captured_monotonic=float(self.ordinal))
            def tap(self, before, **kwargs):
                self.inputs.append(kwargs)
            def reconcile(self, *args):
                pass
        class Session:
            def run_action(self, *, capture, authorize, dispatch, recognize, **kwargs):
                before = capture("fresh-before")
                authorize(before)
                dispatch(before)
                recognize(capture("post"))
        runtime = Runtime()
        route = native.EnhancementIntegratedRoute(runtime, variant="gear", reset_identity="current-reset", session=Session())
        call = lambda: route._action(label="home-to-commander", identity="commander-profile-portrait",
            before_recognizer=lambda capture: native.recognize_home_frame(capture.frame,
                source_frame_sha256=capture.sha256, ocr_engine=lambda *_: hits),
            post_recognizer=lambda capture: SimpleNamespace(recognized=True, reason="unit-tab-successor"),
            target_getter=lambda recognition: recognition.portrait_target)
        return runtime, route, call

    def test_nested_duplicate_consumer_sends_one_current_portrait_navigation(self):
        runtime, route, call = self.dispatch([TIGHT, WIDE, VIP])
        with patch.object(native, "is_clean_home_frame", return_value=True):
            call()
        self.assertEqual([row["target_identity"] for row in runtime.inputs], ["commander-profile-portrait"])
        self.assertEqual(runtime.inputs[0]["target_roi"], native.HOME_PROFILE_PORTRAIT_ROI)
        self.assertFalse(route.resource_dispatch_keys)

    def test_distinct_or_conflicting_badges_stop_before_any_input(self):
        separate = native.OcrHit("47", (53, 66, 76, 81), 95.)
        cases = ([TIGHT, separate, VIP],
            # This broad out-of-admission box must not suppress either of the
            # two real badge witnesses even if it has the highest confidence.
            [TIGHT, separate, native.OcrHit("47", (0, 54, 120, 100), 99.), VIP],
            [TIGHT, native.OcrHit("48", TIGHT.bounds, 99.), VIP],
            [TIGHT, native.OcrHit("4?", TIGHT.bounds, 99.), VIP],
            [TIGHT, VIP, native.OcrHit("VIP11", VIP.bounds, 99.)])
        for hits in cases:
            with self.subTest(hits=hits), patch.object(native, "is_clean_home_frame", return_value=True):
                runtime, route, call = self.dispatch(hits)
                with self.assertRaises(native._FlowBlocked):
                    call()
                self.assertFalse(runtime.inputs)
                self.assertFalse(route.resource_dispatch_keys)


if __name__ == "__main__":
    unittest.main()
