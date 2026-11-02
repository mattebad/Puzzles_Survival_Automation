"""Tesseract's existing timed process, with a shared caller-owned OCR budget."""
from contextvars import ContextVar
import time
from typing import Callable


DEADLINE: ContextVar[float | None] = ContextVar("native_ocr_deadline", default=None)
CHECKPOINT: ContextVar[Callable[[], None] | None] = ContextVar("native_ocr_checkpoint", default=None)
CALL_TIMEOUT_SECONDS = 5.0


class OcrDeadline(RuntimeError):
    pass


def check_budget() -> None:
    checkpoint = CHECKPOINT.get()
    if checkpoint is not None:
        checkpoint()
    deadline = DEADLINE.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise OcrDeadline("OCR_DEADLINE")


def call_ocr(reader, image, *, call_timeout=CALL_TIMEOUT_SECONDS, **options):
    check_budget()
    deadline = DEADLINE.get()
    remaining = call_timeout if deadline is None else min(call_timeout, deadline - time.monotonic())
    if remaining <= 0:
        raise OcrDeadline("OCR_DEADLINE")
    try:
        result = reader(image, timeout=remaining, **options)
    except RuntimeError as exc:
        if str(exc) == "Tesseract process timeout":
            raise OcrDeadline("OCR_DEADLINE") from exc
        raise
    check_budget()
    return result


def tesseract_data(image, *, config: str, timeout: float):
    # image_to_data first runs an unbounded --version probe. Supported Tesseract
    # versions provide TSV; retain its timed process and identical DICT parser.
    from pytesseract.pytesseract import file_to_dict, run_and_get_output
    return file_to_dict(run_and_get_output(image, "tsv",
        config=f"-c tessedit_create_tsv=1 {config.strip()}", timeout=timeout), "\t", -1)
