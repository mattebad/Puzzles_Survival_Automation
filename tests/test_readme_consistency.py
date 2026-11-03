"""The README's route table and status link must match the code and the docs tree."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import unittest

from automation_service.cli import build_parser
from automation_service.registry import CANONICAL_FLOW_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
STATUS_REPORT = re.compile(r"bluestacks-route-status-(\d{8})\.md")
NAVIGATION_ONLY = "navigation_only"


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if match is None:
        raise AssertionError(f"README has no '## {heading}' section")
    return match.group(1)


def _route_rows(text: str) -> list[tuple[str | None, str]]:
    """Return (serve flow or None, registry family) for each route-table row."""

    rows = []
    for line in _section(text, "Routes").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) < 2 or set(cells[0]) <= {"-", " "}:
            continue
        if cells[0] == "`serve --flow`":
            continue
        family = re.fullmatch(r"`([a-z0-9_]+)`", cells[1])
        if family is None:
            raise AssertionError(f"route row has no backticked registry family: {line}")
        flow = re.fullmatch(r"`([a-z0-9-]+)`", cells[0])
        if flow is None and "navigation-only" not in cells[0]:
            raise AssertionError(f"route row has neither a --flow name nor navigation-only: {line}")
        rows.append((flow.group(1) if flow else None, family.group(1)))
    return rows


def _serve_flow_choices() -> set[str]:
    parser = build_parser()
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    serve = subparsers.choices["serve"]
    flow = next(a for a in serve._actions if "--flow" in a.option_strings)
    return set(flow.choices)


class ReadmeConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = README.read_text(encoding="utf-8")
        self.rows = _route_rows(self.text)

    def test_route_table_has_one_row_per_registry_family(self) -> None:
        families = [family for _, family in self.rows]
        self.assertEqual(len(families), len(set(families)), "duplicate route rows")
        self.assertEqual(
            set(families),
            {entry.descriptor.family for entry in CANONICAL_FLOW_REGISTRY},
        )

    def test_only_navigation_only_registrations_lack_a_serve_flow(self) -> None:
        navigation_only = {
            entry.descriptor.family
            for entry in CANONICAL_FLOW_REGISTRY
            if entry.descriptor.variant == NAVIGATION_ONLY
        }
        self.assertEqual({family for flow, family in self.rows if flow is None}, navigation_only)

    def test_route_table_and_serve_example_match_serve_flow_choices(self) -> None:
        choices = _serve_flow_choices()
        self.assertEqual({flow for flow, _ in self.rows if flow is not None}, choices)
        servable = [e for e in CANONICAL_FLOW_REGISTRY if e.descriptor.variant != NAVIGATION_ONLY]
        self.assertEqual(len(choices), len(servable))
        example = set(re.findall(r"--flow ([a-z0-9-]+)", _section(self.text, "Running")))
        self.assertEqual(example, choices)

    def test_current_status_links_to_newest_status_report(self) -> None:
        lines = [line for line in self.text.splitlines() if line.startswith("**Current status:**")]
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
