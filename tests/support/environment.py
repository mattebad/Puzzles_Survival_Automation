"""Explicit optional dependencies for tests that exercise real OCR workers."""

from __future__ import annotations

from functools import wraps
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Callable
import unittest


def _configured_tesseract_command() -> str:
    """Return pytesseract's configured command without invoking it."""

    from pytesseract.pytesseract import tesseract_cmd

    return os.fspath(tesseract_cmd)



def require_tesseract(command: str | os.PathLike[str] | None = None) -> None:
    """Skip a test only when its configured Tesseract executable cannot be resolved."""

    executable = _configured_tesseract_command() if command is None else os.fspath(command)
    if shutil.which(executable) is None:
        raise unittest.SkipTest(
            f"Tesseract executable {executable!r} is unavailable; install Tesseract "
            "or configure pytesseract.pytesseract.tesseract_cmd."
        )


def _guarded_test(
    test: Callable[..., Any], check: Callable[[], None],
) -> Callable[..., Any]:
    @wraps(test)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        check()
        return test(*args, **kwargs)

    return guarded


def requires_tesseract(test: Callable[..., Any]) -> Callable[..., Any]:
    """Gate one real-Tesseract test at call time, leaving mocked tests untouched."""

    return _guarded_test(test, require_tesseract)


def ocr_worker_support_reason(
    *,
    os_name: str | None = None,
    platform: str | None = None,
    proc_stat_path: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return why the bounded OCR worker is unavailable, or ``None`` if supported.

    Optional platform/path arguments make the OS boundary deterministic in tests;
    normal callers use the current interpreter platform and ``/proc/self/stat``.
    Windows is supported through the native Job Object worker implementation.
    """

    current_os = os.name if os_name is None else os_name
    current_platform = sys.platform if platform is None else platform
    if current_os == "nt" and current_platform == "win32":
        return None
    if current_os == "posix" and current_platform.startswith("linux"):
        stat_path = Path("/proc/self/stat" if proc_stat_path is None else proc_stat_path)
        if stat_path.is_file():
            return None
        return f"OCR worker requires Linux /proc/self/stat; {str(stat_path)!r} is unavailable."
    return (
        "OCR worker tests require Linux /proc/self/stat or Windows Job Objects; "
        f"unsupported environment os.name={current_os!r}, "
        f"sys.platform={current_platform!r}."
    )


def require_ocr_worker() -> None:
    """Skip a worker-dependent test only on an unsupported worker platform."""

    reason = ocr_worker_support_reason()
    if reason is not None:
        raise unittest.SkipTest(reason)


def requires_ocr_worker(test: Callable[..., Any]) -> Callable[..., Any]:
    """Gate one test that must launch the bounded OCR worker process."""

    return _guarded_test(test, require_ocr_worker)
