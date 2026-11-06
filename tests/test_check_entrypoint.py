"""The supported developer entrypoint sanitizes its child without hiding failures."""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import check


class CheckEntrypointTests(unittest.TestCase):
    def test_controlled_child_environment_and_fixed_module_selection(self):
        runtime_values = {key: "must-not-reach-child" for key in check._RUNTIME_ENVIRONMENT_KEYS}
        runtime_values.update(PYTHONPATH="foreign", PYTHONHASHSEED="random", PYTHONNOUSERSITE="0")
        with patch.dict(os.environ, runtime_values), patch.object(
            check.subprocess, "run", return_value=SimpleNamespace(returncode=7)
        ) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check.main([]), 7)
            args, kwargs = run.call_args
            self.assertEqual(args[0], [sys.executable, "-m", "unittest", "-v", *check.OFFLINE_TEST_MODULES])
            self.assertEqual(kwargs["cwd"], Path(check.__file__).resolve().parents[1])
            child = kwargs["env"]
            self.assertEqual(child["PYTHONHASHSEED"], "0")
            self.assertEqual(child["PYTHONNOUSERSITE"], "1")
            self.assertEqual(child["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(child["PYTHONPATH"], str(kwargs["cwd"]))
            for key in check._RUNTIME_ENVIRONMENT_KEYS:
                self.assertNotIn(key, child)
                self.assertEqual(os.environ[key], runtime_values[key])

    def test_exit_status_and_spawn_failure_are_not_hidden(self):
        with patch.object(check.subprocess, "run", side_effect=OSError("cannot launch")) as run:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(check.main([]), 1)
            self.assertEqual(run.call_count, 1)
            run.reset_mock()
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                check.main(["--unrecognized-option"])
            self.assertEqual(raised.exception.code, 2)
            run.assert_not_called()

    def test_real_child_imports_repository_under_sanitized_environment(self):
        root = Path(check.__file__).resolve().parents[1]
        source = """import os
from pathlib import Path
import site
import unittest
from scripts import check

class Child(unittest.TestCase):
    def test_environment(self):
        root = Path(check.__file__).resolve().parents[1]
        self.assertEqual(Path.cwd(), root)
        self.assertEqual(os.environ["PYTHONPATH"], str(root))
        self.assertEqual(os.environ["PYTHONHASHSEED"], "0")
        self.assertEqual(os.environ["PYTHONNOUSERSITE"], "1")
        self.assertFalse(site.ENABLE_USER_SITE)
        for key in check._RUNTIME_ENVIRONMENT_KEYS:
            self.assertNotIn(key, os.environ)
"""
        with tempfile.TemporaryDirectory(prefix="offline_entrypoint_", dir=root) as folder:
            directory = Path(folder)
            (directory / "sentinel.py").write_text(source, encoding="utf-8")
            with patch.object(check, "OFFLINE_TEST_MODULES", (directory.name + ".sentinel",)), patch.dict(
                os.environ, {key: "foreign-runtime" for key in check._RUNTIME_ENVIRONMENT_KEYS}
            ), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check.main([]), 0)

