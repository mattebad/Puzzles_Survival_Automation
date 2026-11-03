"""The route-test OCR memo may only replay results real Tesseract produced for the exact input."""
import unittest
from unittest.mock import patch

import numpy as np
import pytesseract.pytesseract as engine

from scripts import bounded_tesseract as bounded
from tests.ocr_memo import OcrMemo


class OcrMemoTests(unittest.TestCase):
    def setUp(self):
        self.runs = []

        def real(image, extension="", lang=None, config="", nice=0, timeout=0, return_bytes=False):
            self.runs.append((image.tobytes(), extension, config))
            if config == "boom":
                raise RuntimeError("Tesseract process timeout")
            return f"run{len(self.runs)}"

        patcher = patch.object(engine, "run_and_get_output", real)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.memo = OcrMemo().start()
        self.addCleanup(self.memo.stop)
        self.frame = np.zeros((4, 6, 3), np.uint8)

    def read(self, image, config="--psm 7"):
        return bounded.call_ocr(bounded.tesseract_string, image, config=config)

    def test_identical_input_and_config_reaches_tesseract_once(self):
        first = self.read(self.frame)
        self.assertEqual(self.read(self.frame.copy()), first)
        self.assertEqual(len(self.runs), 1)
        self.assertEqual((self.memo.misses, self.memo.hits), (1, 1))

    def test_any_pixel_config_or_output_kind_difference_is_a_distinct_input(self):
        self.read(self.frame)
        changed = self.frame.copy()
        changed[0, 0, 0] = 1
        self.read(changed)
        self.read(self.frame, config="--psm 11")
        engine.run_and_get_output(self.frame, "tsv", config="--psm 7")
        self.read(self.frame.reshape(6, 4, 3))
        self.assertEqual(len(self.runs), 5)
        self.assertEqual(self.memo.hits, 0)

    def test_failures_are_never_cached(self):
        for _ in range(2):
            with self.assertRaises(bounded.OcrDeadline):
                self.read(self.frame, config="boom")
        self.assertEqual(len(self.runs), 2)
        self.assertEqual(self.memo.unique_inputs, 0)


if __name__ == "__main__":
    unittest.main()
