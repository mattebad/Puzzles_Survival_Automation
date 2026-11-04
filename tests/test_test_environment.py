"""Deterministic tests for optional test dependencies and worker-platform gates."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pytesseract.pytesseract as pytesseract_engine
import numpy as np

from tests import ocr_memo
from tests.support import environment


class TesseractDependencyTests(unittest.TestCase):
    def test_configured_executable_resolves_without_launch_and_only_missing_tool_skips(self):
        calls = []

        @environment.requires_tesseract
        def dependent_test():
            calls.append("ran")

        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / "tesseract.exe"
            command.write_bytes(b"not a program: executable lookup must not run it")
            command.chmod(0o755)
            with patch.object(pytesseract_engine, "tesseract_cmd", str(command)):
                dependent_test()
                command.unlink()
                with self.assertRaisesRegex(unittest.SkipTest, "tesseract.exe"):
                    dependent_test()
        self.assertEqual(calls, ["ran"])

    def test_missing_executable_is_a_clear_skip_not_an_arbitrary_error(self):
        with patch.object(environment.shutil, "which", return_value=None):
            with self.assertRaisesRegex(unittest.SkipTest, "missing-tesseract") as raised:
                environment.require_tesseract("missing-tesseract")
        self.assertIn("configure pytesseract.pytesseract.tesseract_cmd", str(raised.exception))

    def test_tesseract_decorator_checks_only_its_annotated_test_and_propagates_errors(self):
        calls = []

        @environment.requires_tesseract
        def dependent_test():
            calls.append("ran")

        with patch.object(environment.shutil, "which", return_value=None), \
                patch.object(environment, "_configured_tesseract_command", return_value="not-installed"):
            with self.assertRaisesRegex(unittest.SkipTest, "not-installed"):
                dependent_test()
        self.assertEqual(calls, [])

        with patch.object(environment.shutil, "which", side_effect=AssertionError("resolver failed")), \
                patch.object(environment, "_configured_tesseract_command", return_value="broken-config"):
            with self.assertRaisesRegex(AssertionError, "resolver failed"):
                dependent_test()
        self.assertEqual(calls, [])

    def test_memo_replays_cached_result_but_skips_new_input_when_executable_disappears(self):
        image = np.zeros((2, 3), dtype=np.uint8)
        real = Mock(return_value="recognized")
        with patch.object(pytesseract_engine, "run_and_get_output", real):
            memo = ocr_memo.OcrMemo(require_tesseract_on_miss=True)
        with patch.object(environment.shutil, "which", return_value="resolved-tesseract"):
            initial = memo(image, config="--psm 6")
        with patch.object(environment.shutil, "which", return_value=None):
            self.assertEqual(memo(image.copy(), config="--psm 6"), initial)
            with self.assertRaises(unittest.SkipTest):
                memo(image + 1, config="--psm 6")
        real.assert_called_once()

    def test_memo_skip_prevents_real_call_and_does_not_cache_failure(self):
        image = np.zeros((2, 3), dtype=np.uint8)
        real = Mock(return_value="recognized")
        with patch.object(pytesseract_engine, "run_and_get_output", real):
            memo = ocr_memo.OcrMemo(require_tesseract_on_miss=True)
        with patch.object(environment.shutil, "which", return_value=None):
            with self.assertRaises(unittest.SkipTest):
                memo(image, config="--psm 6")
        real.assert_not_called()
        with patch.object(environment.shutil, "which", return_value="resolved-tesseract"):
            self.assertEqual(memo(image, config="--psm 6"), "recognized")
        real.assert_called_once()


    def test_memo_gates_unkeyable_real_calls_before_execution(self):
        real = Mock(return_value="unreachable")
        with patch.object(pytesseract_engine, "run_and_get_output", real):
            memo = ocr_memo.OcrMemo(require_tesseract_on_miss=True)
            with patch.object(environment.shutil, "which", return_value=None):
                with self.assertRaises(unittest.SkipTest):
                    memo(object())
        real.assert_not_called()


class OcrWorkerPlatformTests(unittest.TestCase):
    def test_linux_requires_proc_stat_but_windows_uses_job_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            stat = Path(directory) / "self" / "stat"
            stat.parent.mkdir()
            stat.write_text("synthetic proc stat", encoding="ascii")
            self.assertIsNone(environment.ocr_worker_support_reason(
                os_name="posix", platform="linux", proc_stat_path=stat,
            ))
            stat.unlink()
            missing_proc = environment.ocr_worker_support_reason(
                os_name="posix", platform="linux", proc_stat_path=stat,
            )
        self.assertIn("/proc/self/stat", missing_proc)
        self.assertIsNone(environment.ocr_worker_support_reason(os_name="nt", platform="win32"))

    def test_only_supported_os_families_pass_and_unsupported_reason_names_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            stat = Path(directory) / "stat"
            stat.write_text("synthetic proc stat", encoding="ascii")
            macos = environment.ocr_worker_support_reason(
                os_name="posix", platform="darwin", proc_stat_path=stat,
            )
            other_posix = environment.ocr_worker_support_reason(
                os_name="posix", platform="freebsd14", proc_stat_path=stat,
            )
        self.assertIn("Linux /proc/self/stat or Windows Job Objects", macos)
        self.assertIn("darwin", macos)
        self.assertIn("freebsd14", other_posix)
        self.assertIsNotNone(environment.ocr_worker_support_reason(
            os_name="nt", platform="win32-posix",
        ))

    def test_worker_decorator_skips_only_its_annotated_test(self):
        calls = []

        @environment.requires_ocr_worker
        def dependent_test():
            calls.append("ran")

        with patch.object(environment, "ocr_worker_support_reason", return_value="unsupported worker platform"):
            with self.assertRaisesRegex(unittest.SkipTest, "unsupported worker platform"):
                dependent_test()
        self.assertEqual(calls, [])
        with patch.object(environment, "ocr_worker_support_reason", return_value=None):
            dependent_test()
        self.assertEqual(calls, ["ran"])



if __name__ == "__main__":
    unittest.main()
