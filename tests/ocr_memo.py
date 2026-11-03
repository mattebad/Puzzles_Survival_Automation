"""Test-side memoization of real Tesseract runs, keyed on the exact input.

Route/service tests replay the same startup/Home frames hundreds of times. This
helper runs the real Tesseract process once per unique (image pixels, extension,
language, config, output type) and replays that real result afterwards, so a
cached answer is always one the real recognizer produced for that exact input.
Production code is untouched: the memo wraps ``pytesseract.pytesseract.
run_and_get_output``, the single function under both ``image_to_string`` and the
TSV path in ``scripts.bounded_tesseract``. Exceptions (including OCR timeouts) are
never cached. Recognition suites that prove OCR on real captures do not install it.
"""
from __future__ import annotations

import hashlib
import threading
import unittest
from unittest.mock import patch

import numpy as np
import pytesseract.pytesseract as engine


def _image_key(image):
    if isinstance(image, np.ndarray):
        return ("ndarray", image.shape, image.dtype.str,
                hashlib.sha256(np.ascontiguousarray(image)).hexdigest())
    if hasattr(image, "tobytes") and hasattr(image, "mode") and hasattr(image, "size"):
        return ("image", image.mode, tuple(image.size), hashlib.sha256(image.tobytes()).hexdigest())
    if isinstance(image, str):
        with open(image, "rb") as handle:
            return ("path", hashlib.sha256(handle.read()).hexdigest())
    return None


class OcrMemo:
    """Memoizes ``run_and_get_output``; ``misses`` counts real Tesseract runs."""

    def __init__(self) -> None:
        self._real = engine.run_and_get_output
        self._results: dict[tuple, str | bytes] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self._patcher = None

    @property
    def unique_inputs(self) -> int:
        return len(self._results)

    def __call__(self, image, extension="", lang=None, config="", nice=0, timeout=0, return_bytes=False):
        image_key = _image_key(image)
        if image_key is None:
            return self._real(image, extension, lang, config, nice, timeout, return_bytes)
        key = (image_key, extension, lang, config, bool(return_bytes))
        with self._lock:
            if key in self._results:
                self.hits += 1
                return self._results[key]
        result = self._real(image, extension, lang, config, nice, timeout, return_bytes)
        with self._lock:
            self._results.setdefault(key, result)
            self.misses += 1
        return result

    def start(self) -> "OcrMemo":
        self._patcher = patch.object(engine, "run_and_get_output", self)
        self._patcher.start()
        return self

    def stop(self) -> None:
        if self._patcher is not None:
            self._patcher.stop()
            self._patcher = None


def install_module_memo() -> OcrMemo:
    """Call from ``setUpModule``; the memo is removed again by the module cleanup."""
    memo = OcrMemo().start()
    unittest.addModuleCleanup(memo.stop)
    return memo
