"""Check active Python code against explicit, non-increasing diagnostic budgets."""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any


STATIC_BASELINE = ".github/static-check-baseline.json"
StaticCounts = Mapping[str, Mapping[str, Mapping[str, int]]]
StaticChanges = dict[tuple[str, str, str], tuple[int, int]]


def budget_changes(current: StaticCounts, allowed: StaticCounts) -> tuple[StaticChanges, StaticChanges]:
    """Return increases and reductions as (old, new), independently per tool/file/rule."""
    increases: StaticChanges = {}
    reductions: StaticChanges = {}
    for tool_name in sorted(current.keys() | allowed.keys()):
        current_files = current.get(tool_name, {})
        allowed_files = allowed.get(tool_name, {})
        for filename in sorted(current_files.keys() | allowed_files.keys()):
            current_rules = current_files.get(filename, {})
            allowed_rules = allowed_files.get(filename, {})
            for rule in sorted(current_rules.keys() | allowed_rules.keys()):
                old, new = allowed_rules.get(rule, 0), current_rules.get(rule, 0)
                if new > old:
                    increases[(tool_name, filename, rule)] = (old, new)
                elif new < old:
                    reductions[(tool_name, filename, rule)] = (old, new)
    return increases, reductions


def static_command(root: Path, arguments: list[str], acceptable: tuple[int, ...] = (0, 1)) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-B", "-m", *arguments], cwd=root,
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode not in acceptable:
        raise RuntimeError(f"{arguments}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def collect_static_findings(root: Path, configuration: dict[str, Any]) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    # Ruff owns the common active-file inventory; Vulture does not introduce a second exclusion list.
    config_path = str(root / "pyproject.toml")
    listed = static_command(root, ["ruff", "check", "--config", config_path, "--show-files", "."], (0,))
    files = [Path(line) for line in listed.stdout.splitlines() if line]
    if not files:
        raise RuntimeError("The active Python file inventory is empty")

    def relative(filename: str | Path) -> str:
        return (root / filename).resolve().relative_to(root).as_posix()

    ruff = static_command(root, ["ruff", "check", "--config", config_path, "--output-format", "json", "."])
    ruff_findings = [
        {"path": relative(row["filename"]), "code": row["code"],
         "message": row["message"], "line": row["location"]["row"]}
        for row in json.loads(ruff.stdout)
    ]
    if ruff.returncode and not ruff_findings:
        raise RuntimeError("Ruff failed without structured diagnostics: " + ruff.stderr)

    # Lazy import: importing the budget arithmetic in unit tests does not start an analyzer.
    import vulture

    unused = vulture.Vulture()
    unused.scavenge([str(path) for path in files])
    if int(unused.exit_code) != 0:
        raise RuntimeError("Vulture could not parse its inputs; findings cannot be treated as complete")
    vulture_findings = [
        {"path": relative(item.filename), "code": f"{item.typ}:{item.confidence}",
         "message": item.message, "line": item.first_lineno}
        for item in unused.get_unused_code(min_confidence=configuration["tool"]["vulture"]["min_confidence"])
    ]

    mypy = static_command(root, [
        "mypy", "--config-file", config_path, "--output", "json", "--no-error-summary", "--no-pretty",
    ])
    mypy_findings = [
        {"path": relative(row["file"]), "code": row["code"], "message": row["message"], "line": row["line"]}
        for row in (json.loads(line) for line in mypy.stdout.splitlines() if line)
        if row["severity"] == "error"
    ]
    if mypy.returncode and not mypy_findings:
        raise RuntimeError("mypy failed without structured errors: " + mypy.stderr)
    type_roots = configuration["tool"]["mypy"]["files"]
    if any(not any(row["path"].startswith(package + "/") for package in type_roots) for row in mypy_findings):
        raise RuntimeError("mypy reported outside the configured safety-package roots")
    return sorted(relative(path) for path in files), {
        "ruff": ruff_findings, "vulture": vulture_findings, "mypy": mypy_findings,
    }


def static_counts(findings: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, dict[str, int]]]:
    counts: dict[str, dict[str, dict[str, int]]] = {}
    for tool_name, rows in findings.items():
        by_file: dict[str, Counter[str]] = {}
        for row in rows:
            by_file.setdefault(row["path"], Counter())[row["code"]] += 1
        counts[tool_name] = {path: dict(sorted(rules.items())) for path, rules in sorted(by_file.items())}
    return counts


def read_static_baseline(value: str) -> dict[str, Any]:
    baseline = json.loads(value)
    tools = {"ruff", "vulture", "mypy"}
    if baseline["schema"] != 1 or set(baseline["counts"]) != tools or set(baseline["versions"]) != tools:
        raise ValueError("Unsupported or incomplete static baseline")
    for files in baseline["counts"].values():
        for rules in files.values():
            if not rules or any(type(count) is not int or count <= 0 for count in rules.values()):
                raise ValueError("Baseline entries must contain positive integer counts; remove zero-debt entries")
    return baseline


def read_static_base_revision(root: Path, revision: str) -> dict[str, Any] | None:
    # ls-tree distinguishes an absent first-introduction baseline from an invalid/unavailable revision.
    listed = subprocess.run(
        ["git", "ls-tree", revision, "--", STATIC_BASELINE], cwd=root,
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    if not listed.stdout:
        return None
    result = subprocess.run(
        ["git", "show", f"{revision}:{STATIC_BASELINE}"], cwd=root,
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return read_static_baseline(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", help="Also forbid budget increases against this immutable Git revision")
    parser.add_argument("--refresh-baseline", action="store_true", help="Record reductions only; never increase a budget")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path = root / STATIC_BASELINE
    try:
        baseline = read_static_baseline(path.read_text(encoding="utf-8"))
        if args.base_ref:
            previous = read_static_base_revision(root, args.base_ref)
            if previous is not None:
                raised, _ = budget_changes(baseline["counts"], previous["counts"])
                if raised:
                    for key, (old, new) in raised.items():
                        print(f"Raised committed budget: {key}: {old} -> {new}", file=sys.stderr)
                    return 1
            else:
                print(f"Initial baseline: {STATIC_BASELINE} is absent at {args.base_ref}")
        versions = {name: importlib.metadata.version(name) for name in baseline["versions"]}
        if versions != baseline["versions"]:
            raise RuntimeError(f"Tool versions differ: {versions}; install requirements-dev.txt")
        configuration = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        files, findings = collect_static_findings(root, configuration)
        counts = static_counts(findings)
        increases, reductions = budget_changes(counts, baseline["counts"])
        print(f"Active Python files: {len(files)}")
        for tool_name, rows in findings.items():
            print(f"{tool_name}: {len(rows)} findings in {len(counts[tool_name])} files")
        if increases:
            for (tool_name, filename, rule), (old, new) in increases.items():
                print(f"{tool_name} {filename} {rule}: {new} findings; budget {old}", file=sys.stderr)
            for tool_name, rows in findings.items():
                for row in rows:
                    if (tool_name, row["path"], row["code"]) in increases:
                        print(f"{row['path']}:{row['line']}: {tool_name} {row['code']}: {row['message']}", file=sys.stderr)
            return 1
        if reductions and not args.refresh_baseline:
            for key, (old, new) in reductions.items():
                print(f"Stale budget: {key}: {old} -> {new}", file=sys.stderr)
            print("Run with --refresh-baseline and commit the reduced budgets", file=sys.stderr)
            return 1
        if reductions:
            baseline["counts"] = counts
            path.write_bytes((json.dumps(baseline, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            print(f"Tightened {len(reductions)} per-file/rule budgets")
        print("Static ratchets passed; no new findings and no stale debt allowances")
        return 0
    except (OSError, ValueError, KeyError, ImportError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Static checks failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
