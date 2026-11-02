"""Bounded native OCR and truthful accounting when recognition cannot finish."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import pytesseract

from scripts import enhancement_bluestacks as native
from scripts.bluestacks_native_runtime import captured_native_frame_from_png


class EnhancementOcrDeadlineTests(unittest.TestCase):
    def capture(self, name="before.png", monotonic=1.):
        ok, png = cv2.imencode(".png", np.zeros((1280, 800, 3), np.uint8))
        self.assertTrue(ok)
        return captured_native_frame_from_png(png.tobytes(),
            path=Path("offline-timeout/frames") / name, captured_monotonic=monotonic)

    def test_stuck_tesseract_is_terminated_without_an_unbounded_version_probe(self):
        original = subprocess.Popen
        children = []
        def hung_process(_command, **options):
            child = original([sys.executable, "-c", "import time; time.sleep(60)"], **options)
            children.append(child)
            return child
        started = time.monotonic()
        try:
            with patch.object(native, "OCR_CALL_TIMEOUT_SECONDS", .1), \
                    patch.object(pytesseract.pytesseract.subprocess, "Popen", side_effect=hung_process), \
                    patch.object(pytesseract.pytesseract, "get_tesseract_version", side_effect=AssertionError("unbounded probe")):
                result = native.recognize_commander_stage(self.capture().frame, variant="gear", stage="material")
            self.assertFalse(result.recognized)
            self.assertEqual(result.reason, "OCR_DEADLINE")
            self.assertIsNone(result.observation)
            self.assertEqual(len(children), 1)
            # Query the OS, not pytesseract's synthetic timeout return code.
            children[0].returncode = None
            self.assertIsNotNone(children[0].poll())
            self.assertLess(time.monotonic() - started, 10)
        finally:
            for child in children:
                child.returncode = None
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)

    def test_one_recognition_shares_its_budget_across_ocr_fields(self):
        frame = cv2.imread(str(Path(__file__).parent / "fixtures/enhancement_item_modal/native-gear-quantity-one-20261029.png"))
        now, timeouts = [100.], []
        original = native._tesseract_data
        def slow_fields(image, *, config, timeout):
            timeouts.append(timeout)
            result = original(image, config=config, timeout=timeout)
            now[0] += 4
            return result
        with patch.object(native.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(native, "_tesseract_data", side_effect=slow_fields):
            result = native.recognize_commander_stage(frame, variant="gear", stage="material")
        self.assertFalse(result.recognized)
        self.assertEqual(result.reason, "OCR_DEADLINE")
        self.assertIsNone(result.quantity_target)
        self.assertGreater(len(timeouts), 1)
        self.assertTrue(all(0 < timeout <= native.OCR_CALL_TIMEOUT_SECONDS for timeout in timeouts))
        self.assertLess(timeouts[-1], timeouts[0])

    def test_shared_home_and_popup_timeouts_cannot_authorize_profile_entry(self):
        from contextlib import ExitStack
        from scripts import startup_normalization
        for at_popup in (False, True):
            with self.subTest(at_popup=at_popup), ExitStack() as stack:
                if at_popup:
                    stack.enter_context(patch.object(startup_normalization, "classify_home_base_live",
                        return_value={"state": "HOME_BASE", "recognized": True}))
                stack.enter_context(patch.object(pytesseract, "image_to_string",
                    side_effect=RuntimeError("Tesseract process timeout")))
                result = native.recognize_home_frame(self.capture().frame)
                self.assertFalse(result.recognized)
                self.assertEqual(result.reason, "OCR_DEADLINE")
                self.assertIsNone(result.portrait_target)

    def action(self, *, timeout_after_dispatch):
        capture = self.capture()
        runtime = SimpleNamespace(input_count=0, events=[], capture=lambda _label: capture)
        def tap(*_args, **_options):
            runtime.input_count += 1
        runtime.tap = tap
        class Session:
            def run_action(self, *, capture, authorize, dispatch, recognize, **_options):
                source = capture("before")
                authorize(source)
                dispatch(source)
                recognize(capture("after"))
        route = native.EnhancementIntegratedRoute(runtime, session=Session(), variant="gear", reset_identity="offline-reset")
        allowed = native.StageRecognition("material", True, "fixture_authorized", capture.sha256)
        def recognize(frame):
            return native.recognize_commander_stage(frame.frame, variant="gear", stage="material")
        with patch.object(native, "_tesseract_data", side_effect=RuntimeError("Tesseract process timeout")):
            if timeout_after_dispatch:
                _after, result = route._action(label="confirm", identity="enhancement-use",
                    before_recognizer=lambda _frame: allowed, post_recognizer=recognize,
                    target_getter=lambda _result: (10, 10, 20, 20), resource_affecting=True)
                self.assertFalse(result.recognized)
                self.assertEqual(result.reason, "OCR_DEADLINE")
                self.assertEqual(runtime.input_count, 1)
                self.assertEqual(len(route.resource_dispatch_keys), 1)
                self.assertFalse(route._result(status="evidence_required", reason=result.reason, source=capture)["terminal_recognized"])
            else:
                with self.assertRaises(native._FlowBlocked):
                    route._action(label="confirm", identity="enhancement-use",
                        before_recognizer=recognize, post_recognizer=recognize,
                        target_getter=lambda _result: (10, 10, 20, 20), resource_affecting=True)
                self.assertEqual(runtime.input_count, 0)
                self.assertEqual(route.resource_dispatch_keys, [])

    def test_timeout_before_confirmation_sends_no_input(self):
        self.action(timeout_after_dispatch=False)

    def test_timeout_after_confirmation_keeps_attempt_and_never_repeats_it(self):
        self.action(timeout_after_dispatch=True)

    def test_cancellation_is_checked_after_ocr_before_any_further_work(self):
        stopped = [False]
        def checkpoint():
            if stopped[0]:
                raise native._FlowBlocked("operator stopped")
        def reader(_image, **_options):
            stopped[0] = True
            return "1/100"
        token = native._OCR_CHECKPOINT.set(checkpoint)
        try:
            with self.assertRaises(native._FlowBlocked):
                native._call_ocr(reader, np.zeros((10, 10), np.uint8))
        finally:
            native._OCR_CHECKPOINT.reset(token)


if __name__ == "__main__":
    unittest.main()
