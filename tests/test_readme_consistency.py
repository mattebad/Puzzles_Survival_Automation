"""The README's status link must point at the newest route status report.

The README route table and `serve --flow` example are checked against the registry in
``tests/test_route_metadata_consistency.py``.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
STATUS_REPORT = re.compile(r"bluestacks-route-status-(\d{8})\.md")


class ReadmeStatusLinkTests(unittest.TestCase):
    def test_current_status_links_to_newest_status_report(self) -> None:
        text = README.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line.startswith("**Current status:**")]
        self.assertEqual(len(lines), 1, "README needs exactly one '**Current status:**' line")
        links = re.findall(r"\]\(([^)]+)\)", lines[0])
        self.assertEqual(len(links), 1, lines[0])
        target = (ROOT / links[0]).resolve()
        self.assertTrue(target.is_file(), f"status link does not resolve: {links[0]}")
        reports = [p for p in (ROOT / "docs").glob("bluestacks-route-status-*.md") if STATUS_REPORT.fullmatch(p.name)]
        self.assertTrue(reports)
        newest = max(reports, key=lambda p: STATUS_REPORT.fullmatch(p.name).group(1))
        self.assertEqual(target, newest.resolve())


if __name__ == "__main__":
    unittest.main()
