"""Execute an explicit offline selection and verify actual execution receipts."""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
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
    """Assign each selected module once, preserving its fixture lifecycle."""
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
    return [sorted(shard) for shard in shards]


def select_suite(
    suite: unittest.TestSuite, modules: Iterable[str], case_ids: Iterable[str] | None = None,
) -> unittest.TestSuite:
    selected = set(modules)
    intended = None if case_ids is None else set(case_ids)
    return unittest.TestSuite(
        case for case in _cases(suite)
        if case.__class__.__module__ in selected
        and (intended is None or case.id() in intended)
    )


class ExecutionResult(unittest.TextTestResult):
    """Record actual starts; a planned list is not execution evidence."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.executed_ids: list[str] = []

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self.executed_ids.append(test.id())


def validate_receipts(
    receipts: Sequence[Mapping[str, Any]], *, count: int,
    platform_name: str, allowed_skips: Iterable[str], revision: str | None = None,
    expected_plan: Mapping[str, Any] | None = None,
    run_attempt: str | None = None,
) -> tuple[int, int]:
    """Require the independently computed plan, successful starts and no new skips.

    Schema-one historical/full receipts remain usable by existing offline callers.
    Current schema-two selected receipts require an independently computed plan.
    """
    if count < 1 or len(receipts) != count:
        raise ValueError(f"Expected {count} shard receipts, received {len(receipts)}")
    indexes: set[int] = set()
    inventory: Counter[str] | None = None
    expected: Counter[str] | None = None
    if expected_plan is not None:
        inventory = Counter(expected_plan["discovered_ids"])
        expected = Counter(expected_plan["planned_ids"])
        if not inventory or any(copies != 1 for copies in inventory.values()):
            raise ValueError("Invalid independently discovered inventory")
        if not expected or any(copies != 1 for copies in expected.values()) or expected - inventory:
            raise ValueError("Invalid independently intended execution")
        if Counter(expected_plan["omitted_ids"]) != inventory - expected:
            raise ValueError("Independent plan does not disclose its exact omissions")
        if expected_plan["profile"] in {"full", "full-fallback"} and expected != inventory:
            raise ValueError("Partial execution cannot be labelled full coverage")
    executed: Counter[str] = Counter()
    skipped: list[str] = []
    for receipt in receipts:
        index = receipt["index"]
        schema = receipt["schema"]
        if (schema not in {1, 2} or receipt["count"] != count
                or receipt["platform"] != platform_name
                or type(index) is not int or not 0 <= index < count
                or index in indexes):
            raise ValueError("Inconsistent or duplicate shard receipt")
        indexes.add(index)
        if revision is not None and receipt["revision"] != revision:
            raise ValueError("Shard receipt belongs to another revision")
        if run_attempt is not None and receipt.get("run_attempt") != run_attempt:
            raise ValueError("Shard receipt belongs to another workflow attempt")
        discovered = Counter(receipt["discovered_ids"])
        duplicate_ids = [name for name, copies in discovered.items() if copies > 1]
        if duplicate_ids:
            raise ValueError("Duplicate discovered test IDs: " + ", ".join(sorted(duplicate_ids)))
        if inventory is None:
            inventory = discovered
        elif discovered != inventory:
            raise ValueError("Shards discovered different test inventories")
        if schema == 2:
            if expected_plan is None:
                raise ValueError("Selected receipts require an independent execution plan")
            for field in ("profile", "planned_ids", "omitted_ids", "changed_paths", "policy_sha256"):
                if receipt[field] != expected_plan[field]:
                    raise ValueError("Receipt differs from independent plan: " + field)
        elif expected_plan is not None:
            raise ValueError("Current execution requires a selection-aware receipt")
        if expected is None:
            expected = discovered
        actual = Counter(receipt["executed_ids"])
        if (receipt["success"] is not True or receipt["failures"] or receipt["errors"]
                or actual != Counter(receipt["selected_ids"])
                or receipt["tests_run"] != actual.total()):
            raise ValueError(f"Shard {index} failed or did not execute its selected cases")
        shard_skips = Counter(receipt["skipped_ids"])
        if shard_skips - actual or any(copies != 1 for copies in shard_skips.values()):
            raise ValueError("Skip receipt contains unexecuted or repeated cases")
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


def discover_suite() -> tuple[unittest.TestSuite, list[str], int]:
    directory = REPO_ROOT / "tests"
    loader = unittest.TestLoader()
    suite = loader.discover(str(directory), pattern="test_*.py", top_level_dir=str(REPO_ROOT))
    if loader.errors:
        raise ValueError("\n".join(loader.errors))
    module_count, _ = validate_discovery(directory, suite)
    return suite, [case.id() for case in _cases(suite)], module_count


def changed_paths(base_ref: str | None) -> list[str] | None:
    """Missing/unavailable history requests the explicit broad fallback."""
    if not base_ref or set(base_ref) == {"0"}:
        return None
    try:
        result = subprocess.run(
            ["git", "diff", "--no-renames", "--name-only", "-z", f"{base_ref}...HEAD"],
            cwd=REPO_ROOT, capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return sorted(path for path in result.stdout.decode("utf-8").split("\0") if path)


def execution_plan(
    discovered_ids: list[str], *, profile: str, base_ref: str | None,
    platform_name: str,
) -> dict[str, Any]:
    from scripts.offline_selection import build_selection

    paths = changed_paths(base_ref) if profile == "routine" else []
    if profile == "full":
        intended, omitted, reasons, resolved_profile = discovered_ids, [], ["explicit full validation"], "full"
    else:
        selection = build_selection(discovered_ids, paths, platform_name, REPO_ROOT)
        intended = list(selection.intended_ids)
        omitted = list(selection.omitted_ids)
        reasons = list(selection.reasons)
        resolved_profile = selection.profile
    return {
        "profile": resolved_profile, "discovered_ids": discovered_ids,
        "planned_ids": intended, "omitted_ids": omitted, "changed_paths": paths,
        "reasons": reasons,
        "policy_sha256": hashlib.sha256(
            (REPO_ROOT / "scripts/offline_selection.py").read_bytes()
        ).hexdigest(),
    }


def run_shard(args: argparse.Namespace, costs: Mapping[str, Any]) -> int:
    if not 0 <= args.index < args.count:
        raise ValueError("Shard index must be within the shard count")
    started = time.perf_counter()
    suite, discovered_ids, module_count = discover_suite()
    plan = execution_plan(
        discovered_ids, profile=args.profile, base_ref=args.base_ref,
        platform_name=platform.system(),
    )
    intended = set(plan["planned_ids"])
    modules = {
        case.__class__.__module__ for case in _cases(suite) if case.id() in intended
    }
    shards = partition_modules(
        modules, costs["module_seconds"], args.count,
        reserved_seconds=float(costs["reserved_seconds"]),
    )
    selected = select_suite(suite, shards[args.index], intended)
    selected_ids = [case.id() for case in _cases(selected)]
    del suite
    selection_seconds = time.perf_counter() - started
    print(
        f"{plan['profile']}: shard {args.index + 1}/{args.count} executes "
        f"{len(selected_ids)} of {len(plan['planned_ids'])} intended cases; "
        f"inventory {module_count} modules / {len(discovered_ids)} cases; "
        f"{len(plan['omitted_ids'])} explicitly deferred.",
        flush=True,
    )
    print("Selection: " + "; ".join(plan["reasons"]), flush=True)
    suite_started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=ExecutionResult).run(selected)
    receipt = {
        **plan, "schema": 2, "index": args.index, "count": args.count,
        "platform": platform.system(), "revision": os.environ.get("GITHUB_SHA"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "selected_ids": selected_ids, "executed_ids": result.executed_ids,
        "tests_run": result.testsRun, "success": result.wasSuccessful(),
        "failures": [case.id() for case, _ in result.failures],
        "errors": [case.id() for case, _ in result.errors],
        "skipped_ids": [case.id() for case, _ in result.skipped],
        "selection_seconds": round(selection_seconds, 3),
        "suite_seconds": round(time.perf_counter() - suite_started, 3),
        "seconds": round(time.perf_counter() - started, 3),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


def main(argv: Sequence[str] | None = None) -> int:
    from scripts.check import controlled_environment

    # CI also sets interpreter-startup flags before Python starts. Scrub device
    # selectors before discovery/imports, instead of repeating the semantic suite
    # in a second, differently configured child process.
    environment = controlled_environment(REPO_ROOT)
    os.environ.clear()
    os.environ.update(environment)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--costs", type=Path, default=REPO_ROOT / ".github/offline-test-costs.json")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Execute one slice of the declared offline selection")
    run.add_argument("--index", type=int, required=True)
    run.add_argument("--count", type=int, required=True)
    run.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="Verify actual execution against a recomputed selection")
    verify.add_argument("--reports", type=Path, required=True)
    verify.add_argument("--count", type=int, required=True)
    verify.add_argument("--platform", choices=("Linux", "Windows"), required=True)
    for command in (run, verify):
        command.add_argument("--profile", choices=("full", "routine"), default="full")
        command.add_argument("--base-ref")
    args = parser.parse_args(argv)
    try:
        costs = json.loads(args.costs.read_text(encoding="utf-8"))
        if args.command == "run":
            return run_shard(args, costs)
        _, discovered_ids, _ = discover_suite()
        plan = execution_plan(
            discovered_ids, profile=args.profile, base_ref=args.base_ref,
            platform_name=args.platform,
        )
        receipts = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(args.reports.glob("*.json"))
        ]
        cases, skips = validate_receipts(
            receipts, count=args.count, platform_name=args.platform,
            allowed_skips=costs["allowed_skips"][args.platform],
            revision=os.environ.get("GITHUB_SHA"), expected_plan=plan,
            run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(
        f"Verified {plan['profile']}: all {cases} intended cases executed exactly once "
        f"on {args.platform}; inventory {len(discovered_ids)}, "
        f"explicitly deferred {len(plan['omitted_ids'])}; "
        f"{skips} baseline skips, no new skips."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
