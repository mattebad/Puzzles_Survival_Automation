"""Test-side memoization of real Tesseract runs, keyed on the exact input.

Route/service tests replay the same startup/Home frames hundreds of times. This
helper runs the real Tesseract process once per unique (image pixels, extension,
language, config, nice, output type) and replays that real result afterwards, so a
cached answer is always one the real recognizer produced for that exact input.
A replay also honours the caller's ``timeout``: deadline-derived timeouts differ on
every call, so they are not part of the key; instead a call whose timeout is
shorter than the recorded real run goes back to real Tesseract and times out there.
Production code is untouched: the memo wraps ``pytesseract.pytesseract.
run_and_get_output``, the single function under both ``image_to_string`` and the
TSV path in ``scripts.bounded_tesseract``. Exceptions (including OCR timeouts) are
never cached. Recognition suites that prove OCR on real captures do not install it.
"""
from __future__ import annotations

import hashlib
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
import pytesseract.pytesseract as engine

from tests.support.environment import require_tesseract


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
    """Memoizes OCR; installed instances gate executable availability on real misses."""

    def __init__(self, *, require_tesseract_on_miss: bool = False) -> None:
        self._real = engine.run_and_get_output
        self._require_tesseract_on_miss = require_tesseract_on_miss
        self._results: dict[tuple, tuple[str | bytes, float]] = {}
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
            if self._require_tesseract_on_miss:
                require_tesseract()
            return self._real(image, extension, lang, config, nice, timeout, return_bytes)
        key = (image_key, extension, lang, config, nice, bool(return_bytes))
        with self._lock:
            cached = self._results.get(key)
            if cached is not None and (not timeout or cached[1] <= timeout):
                self.hits += 1
                return cached[0]
        if self._require_tesseract_on_miss:
            require_tesseract()
        started = time.monotonic()
        result = self._real(image, extension, lang, config, nice, timeout, return_bytes)
        elapsed = time.monotonic() - started
        with self._lock:
            self._results.setdefault(key, (result, elapsed))
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
    """Install a Tesseract-gated memo from ``setUpModule`` and clean it up afterward."""

    memo = OcrMemo(require_tesseract_on_miss=True).start()
    unittest.addModuleCleanup(memo.stop)
    return memo
