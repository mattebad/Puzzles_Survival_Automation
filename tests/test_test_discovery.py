"""Behavioral coverage checks against real unittest discovery."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_test_discovery import validate_discovery


TEST_MODULE = """import unittest
class Example(unittest.TestCase):
    def test_behavior(self):
        self.fail("discovery must not execute fixture test bodies")
"""


class DiscoveryCoverageTests(unittest.TestCase):
    def discover(self, sources):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        directory = root / "fixture_suite"
        directory.mkdir()
        (directory / "__init__.py").write_text("", encoding="utf-8")
        for name, source in sources.items():
            (directory / name).write_text(source, encoding="utf-8")
        with patch.dict(sys.modules), patch.object(sys, "path", list(sys.path)):
            loader = unittest.TestLoader()
            suite = loader.discover(str(directory), pattern="test_*.py", top_level_dir=str(root))
        self.assertEqual(loader.errors, [])
        return directory, suite

    def test_all_discovered_modules_are_counted(self):
        directory, suite = self.discover({"test_first.py": TEST_MODULE, "test_second.py": TEST_MODULE})
        self.assertEqual(validate_discovery(directory, suite), (2, 2))

    def test_empty_module_cannot_silently_disappear(self):
        directory, suite = self.discover({"test_first.py": TEST_MODULE, "test_empty.py": ""})
        with self.assertRaises(RuntimeError) as caught:
            validate_discovery(directory, suite)
        self.assertIn("fixture_suite.test_empty", str(caught.exception))

    def test_load_tests_cannot_hide_a_modules_cases(self):
        hidden = TEST_MODULE + "\ndef load_tests(loader, tests, pattern):\n    return unittest.TestSuite()\n"
        directory, suite = self.discover({"test_first.py": TEST_MODULE, "test_hidden.py": hidden})
        with self.assertRaises(RuntimeError) as caught:
            validate_discovery(directory, suite)
        self.assertIn("fixture_suite.test_hidden", str(caught.exception))
