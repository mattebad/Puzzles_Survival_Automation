"""Architecture guard: production OCR runs only through the bounded engine.

Every production Tesseract call must go through ``scripts.bounded_tesseract``
(shared deadline, per-call timeout, fail-closed ``OcrDeadline``) or the
identity-bound worker in ``tasks.semantic_ocr_crop``. Importing ``pytesseract``
anywhere else bypasses those bounds, so this test fails on any such import.
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import bounded_tesseract as engine

REPO_ROOT = Path(__file__).resolve().parents[1]

# The only modules allowed to import pytesseract.
BOUNDED_ENGINE_MODULES = frozenset({
    "scripts/bounded_tesseract.py",
    "tasks/semantic_ocr_crop.py",
})
# Reviewed exceptions: path -> reason. Empty: every other caller is migrated.
REVIEWED_EXCEPTIONS: dict[str, str] = {}

_EXCLUDED_TOP_LEVEL = frozenset({"tests", "evidence", "docs", "examples"})
_PYTESSERACT = "pytesseract"


def _is_pytesseract(name: str | None) -> bool:
    return name == _PYTESSERACT or (name or "").startswith(_PYTESSERACT + ".")


def direct_pytesseract_uses(source: str) -> list[int]:
    """Return line numbers of real imports of pytesseract (comments/strings never count)."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(_is_pytesseract(alias.name) for alias in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and _is_pytesseract(node.module):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call):
            function = node.func
            name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", None)
            if name in {"import_module", "__import__"} and node.args:
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and _is_pytesseract(argument.value):
                    lines.append(node.lineno)
    return sorted(lines)


def production_python_files() -> list[Path]:
    files = []
    for path in REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT)
        if relative.parts[0] in _EXCLUDED_TOP_LEVEL or any(
            part.startswith(".") or part == "__pycache__" for part in relative.parts
        ):
            continue
        files.append(path)
    return sorted(files)


class BoundedOcrArchitectureTests(unittest.TestCase):
    def test_no_direct_pytesseract_use_outside_bounded_engine(self) -> None:
        allowed = BOUNDED_ENGINE_MODULES | frozenset(REVIEWED_EXCEPTIONS)
        violations = {}
        for path in production_python_files():
            relative = path.relative_to(REPO_ROOT).as_posix()
            if relative in allowed:
                continue
            lines = direct_pytesseract_uses(path.read_text(encoding="utf-8"))
            if lines:
                violations[relative] = lines
        self.assertEqual(violations, {}, "route OCR through scripts.bounded_tesseract")

    def test_allowed_modules_exist_and_still_need_their_allowance(self) -> None:
        for relative in sorted(BOUNDED_ENGINE_MODULES | frozenset(REVIEWED_EXCEPTIONS)):
            with self.subTest(module=relative):
                path = REPO_ROOT / relative
                self.assertTrue(path.is_file())
                self.assertTrue(direct_pytesseract_uses(path.read_text(encoding="utf-8")))
        for relative, reason in REVIEWED_EXCEPTIONS.items():
            self.assertTrue(reason.strip(), relative)

    def test_scanner_flags_imports_and_ignores_comments_and_strings(self) -> None:
        flagged = (
            "import pytesseract\n",
            "import pytesseract.pytesseract as engine\n",
            "from pytesseract import image_to_string\n",
            "from pytesseract.pytesseract import run_tesseract\n",
            "def f():\n    import pytesseract\n",
            "import importlib\nimportlib.import_module('pytesseract')\n",
            "__import__('pytesseract')\n",
        )
        for source in flagged:
            with self.subTest(source=source):
                self.assertTrue(direct_pytesseract_uses(source))
        ignored = (
            "# import pytesseract\n",
            "'''import pytesseract.image_to_string(x)'''\n",
            "text = 'pytesseract.image_to_string'\n",
            "from . import pytesseract_helpers\n",
            "from scripts.bounded_tesseract import tesseract_string\n",
        )
        for source in ignored:
            with self.subTest(source=source):
                self.assertEqual(direct_pytesseract_uses(source), [])


class BoundedEngineFailClosedTests(unittest.TestCase):
    def test_string_reader_passes_remaining_budget_and_returns_text(self) -> None:
        with patch("pytesseract.image_to_string", return_value="Claim") as reader:
            text = engine.call_ocr(engine.tesseract_string, object(), config="--psm 7", call_timeout=2)
        self.assertEqual(text, "Claim")
        self.assertEqual(reader.call_args.kwargs["config"], "--psm 7")
        self.assertLessEqual(reader.call_args.kwargs["timeout"], 2)
        self.assertGreater(reader.call_args.kwargs["timeout"], 0)

    def test_process_timeout_becomes_deadline_not_text(self) -> None:
        with patch("pytesseract.image_to_string", side_effect=RuntimeError("Tesseract process timeout")):
            with self.assertRaises(engine.OcrDeadline):
                engine.call_ocr(engine.tesseract_string, object(), config="--psm 7")

    def test_other_engine_errors_propagate_without_text(self) -> None:
        with patch("pytesseract.image_to_string", side_effect=RuntimeError("tesseract failed")):
            with self.assertRaisesRegex(RuntimeError, "tesseract failed"):
                engine.call_ocr(engine.tesseract_string, object(), config="--psm 7")


if __name__ == "__main__":
    unittest.main()
