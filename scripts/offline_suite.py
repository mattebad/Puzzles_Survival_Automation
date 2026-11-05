"""Run a measured slice of full discovery, then verify all CI slices together."""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.check_test_discovery import _cases, validate_discovery  # noqa: E402


def partition_modules(
    modules: Iterable[str], weights: Mapping[str, float], count: int,
    *, reserved_seconds: float = 0,
) -> list[list[str]]:
    """Assign every current module, including modules absent from old timings."""
    if count < 1 or not math.isfinite(reserved_seconds) or reserved_seconds < 0:
        raise ValueError("Invalid shard count or reserved cost")
    costs = {name: float(weights.get(name, 1)) for name in set(modules)}
    if any(not math.isfinite(cost) or cost < 0 for cost in costs.values()):
        raise ValueError("Module costs must be finite and nonnegative")
    shards: list[list[str]] = [[] for _ in range(count)]
    loads = [reserved_seconds, *([0.0] * (count - 1))]
    for name in sorted(costs, key=lambda name: (-costs[name], name)):
        index = min(range(count), key=lambda index: (loads[index], index))
        shards[index].append(name)
        loads[index] += costs[name]
    # Preserve discovery's module order and its class/module fixture boundaries.
    return [sorted(shard) for shard in shards]


def select_suite(suite: unittest.TestSuite, modules: Iterable[str]) -> unittest.TestSuite:
    selected = set(modules)
    return unittest.TestSuite(
        case for case in _cases(suite)
        if case.__class__.__module__ in selected
    )


class ExecutionResult(unittest.TextTestResult):
    """Record actual starts, not merely the cases intended for execution."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.executed_ids: list[str] = []

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self.executed_ids.append(test.id())


def validate_receipts(
    receipts: Sequence[Mapping[str, Any]], *, count: int,
    platform_name: str, allowed_skips: Iterable[str], revision: str | None = None,
) -> tuple[int, int]:
    """Reject absent, overlapping, incomplete, failed or newly skipped coverage."""
    if count < 1 or len(receipts) != count:
        raise ValueError(f"Expected {count} shard receipts, received {len(receipts)}")
    indexes: set[int] = set()
    expected: Counter[str] | None = None
    executed: Counter[str] = Counter()
    skipped: list[str] = []
    for receipt in receipts:
        index = receipt["index"]
        if (receipt["schema"] != 1 or receipt["count"] != count
                or receipt["platform"] != platform_name
                or not isinstance(index, int) or not 0 <= index < count
                or index in indexes):
            raise ValueError("Inconsistent or duplicate shard receipt")
        indexes.add(index)
        if revision is not None and receipt["revision"] != revision:
            raise ValueError("Shard receipt belongs to another revision")
        discovered = Counter(receipt["discovered_ids"])
        duplicate_ids = [name for name, copies in discovered.items() if copies > 1]
        if duplicate_ids:
            raise ValueError("Duplicate discovered test IDs: " + ", ".join(sorted(duplicate_ids)))
        if expected is None:
            expected = discovered
        elif discovered != expected:
            raise ValueError("Shards discovered different test inventories")
        actual = Counter(receipt["executed_ids"])
        if (receipt["success"] is not True or receipt["failures"] or receipt["errors"]
                or actual != Counter(receipt["selected_ids"])
                or receipt["tests_run"] != actual.total()):
            raise ValueError(f"Shard {index} failed or did not execute its selected cases")
        executed.update(actual)
        skipped.extend(receipt["skipped_ids"])
    if not expected or executed != expected:
        missing = list((expected or Counter()) - executed)
        repeated = list(executed - (expected or Counter()))
        raise ValueError(f"Coverage mismatch: missing={missing}, repeated={repeated}")
    new_skips = set(skipped) - set(allowed_skips)
    if new_skips:
        raise ValueError("New skipped cases: " + ", ".join(sorted(new_skips)))
    return executed.total(), len(skipped)


def run_shard(args: argparse.Namespace, costs: Mapping[str, Any]) -> int:
    if not 0 <= args.index < args.count:
        raise ValueError("Shard index must be within the shard count")
    started = time.perf_counter()
    directory = REPO_ROOT / "tests"
    loader = unittest.TestLoader()
    suite = loader.discover(str(directory), pattern="test_*.py", top_level_dir=str(REPO_ROOT))
    if loader.errors:
        raise ValueError("\n".join(loader.errors))
    module_count, _ = validate_discovery(directory, suite)
    discovered_cases = list(_cases(suite))
    discovered_ids = [case.id() for case in discovered_cases]
    plan = partition_modules(
        (case.__class__.__module__ for case in discovered_cases),
        costs["module_seconds"], args.count,
        reserved_seconds=float(costs["reserved_seconds"]),
    )
    selected = select_suite(suite, plan[args.index])
    selected_ids = [case.id() for case in _cases(selected)]
    del discovered_cases, suite
    print(f"Shard {args.index + 1}/{args.count}: {len(selected_ids)} of "
          f"{len(discovered_ids)} cases; discovery covers all {module_count} modules.", flush=True)
    result = unittest.TextTestRunner(verbosity=2, resultclass=ExecutionResult).run(selected)
    receipt = {
        "schema": 1, "index": args.index, "count": args.count,
        "platform": platform.system(), "revision": os.environ.get("GITHUB_SHA"),
        "discovered_ids": discovered_ids, "selected_ids": selected_ids,
        "executed_ids": result.executed_ids, "tests_run": result.testsRun,
        "success": result.wasSuccessful(),
        "failures": [case.id() for case, _ in result.failures],
        "errors": [case.id() for case, _ in result.errors],
        "skipped_ids": [case.id() for case, _ in result.skipped],
        "seconds": round(time.perf_counter() - started, 3),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--costs", type=Path, default=REPO_ROOT / ".github/offline-test-costs.json")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Execute one whole-module slice of complete discovery")
    run.add_argument("--index", type=int, required=True)
    run.add_argument("--count", type=int, required=True)
    run.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="Require exact execution coverage across all slices")
    verify.add_argument("--reports", type=Path, required=True)
    verify.add_argument("--count", type=int, required=True)
    verify.add_argument("--platform", choices=("Linux", "Windows"), required=True)
    args = parser.parse_args(argv)
    try:
        costs = json.loads(args.costs.read_text(encoding="utf-8"))
        if args.command == "run":
            return run_shard(args, costs)
        receipts = [json.loads(path.read_text(encoding="utf-8"))
                    for path in sorted(args.reports.glob("*.json"))]
        cases, skips = validate_receipts(
            receipts, count=args.count, platform_name=args.platform,
            allowed_skips=costs["allowed_skips"][args.platform],
            revision=os.environ.get("GITHUB_SHA"),
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(f"All {cases} discovered cases executed exactly once on {args.platform}; "
          f"{skips} baseline skips, no new skips.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
