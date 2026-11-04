"""Fail CI if unittest discovery omits any top-level test module."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from collections.abc import Iterator


def _cases(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _cases(test)
        else:
            yield test


def validate_discovery(directory: Path, suite: unittest.TestSuite) -> tuple[int, int]:
    """Return module/case counts, rejecting empty or hidden test modules.

    No modules are excluded. Any future exclusion needs an explicit reviewed
    change here rather than silently shrinking a hand-maintained CI list.
    """
    expected = {f"{directory.name}.{path.stem}" for path in directory.glob("test_*.py")}
    cases = list(_cases(suite))
    observed = {".".join(case.id().split(".", 2)[:2]) for case in cases}
    missing = expected - observed
    if missing:
        raise RuntimeError("Test modules omitted by discovery: " + ", ".join(sorted(missing)))
    return len(expected), len(cases)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    directory = root / "tests"
    loader = unittest.TestLoader()
    suite = loader.discover(str(directory), pattern="test_*.py", top_level_dir=str(root))
    if loader.errors:
        for error in loader.errors:
            print(error, file=sys.stderr)
        return 1
    try:
        modules, cases = validate_discovery(directory, suite)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Discovery covers all {modules} test modules ({cases} cases); no exclusions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
