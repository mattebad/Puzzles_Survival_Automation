"""Ticket #24 diagnostic receipts; the required gate is full unittest discovery."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.machinery
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = {"adb", "hd-adb", "ssh", "scp", "plink", "hd-player", "bluestacks", "scrcpy", "vboxmanage", "vmrun", "virsh"}


def provenance(target_root: Path, source_commit: str | None, driver_commit: str | None) -> dict:
    return {
        "test_source": {"root": str(target_root), "commit": source_commit},
        "driver": {"path": str(Path(__file__).resolve()), "root": str(ROOT), "commit": driver_commit},
        "event": {"commit": os.environ.get("GITHUB_SHA")},
    }


def module_source(module: str, target_root: Path) -> str | None:
    if module == "full":
        return None
    return str(target_root.joinpath(*module.split(".")).with_suffix(".py"))


def install_baseline_namespace(target_root: Path) -> str:
    tests_root = target_root / "tests"
    if (tests_root / "__init__.py").is_file():
        return "filesystem_tests_package"
    namespace = types.ModuleType("tests")
    namespace.__path__ = [str(tests_root)]
    namespace.__package__ = "tests"
    namespace.__spec__ = importlib.machinery.ModuleSpec("tests", loader=None, is_package=True)
    namespace.__spec__.submodule_search_locations = [str(tests_root)]
    sys.modules["tests"] = namespace
    return "in_memory_tests_namespace"


def child(
    module: str,
    destination: Path,
    target_root: Path = ROOT,
    baseline_namespace: bool = False,
    source_commit: str | None = None,
    driver_commit: str | None = None,
) -> int:
    target_root = target_root.resolve()
    os.chdir(target_root)
    sys.path.insert(0, str(target_root))
    source_commit = source_commit or (os.environ.get("GITHUB_SHA") if target_root == ROOT else None)
    driver_commit = driver_commit or os.environ.get("TICKET24_DRIVER_COMMIT") or os.environ.get("GITHUB_SHA")
    namespace_mode = "not_used_for_full_discovery" if module == "full" else "disabled"
    if module != "full" and baseline_namespace:
        namespace_mode = install_baseline_namespace(target_root)
    popen = subprocess.Popen
    attempts = []

    def offline_popen(command, *args, **kwargs):
        executable = kwargs.get("executable") or (command[0] if isinstance(command, (list, tuple)) else str(command).split()[0])
        if Path(str(executable).strip('"')).stem.casefold() in FORBIDDEN:
            attempts.append(str(executable))
            raise AssertionError("live/device executable forbidden in #24 offline proof")
        return popen(command, *args, **kwargs)

    selection = ["discover", "-v", "-s", "tests", "-t", "."] if module == "full" else ["-v", module]
    started = time.monotonic()
    with patch.object(subprocess, "Popen", offline_popen):
        result = unittest.main(module=None, argv=["unittest", *selection], exit=False).result
    receipt = {
        "module": module,
        "source_file": module_source(module, target_root),
        "source_commit": source_commit,
        "provenance": provenance(target_root, source_commit, driver_commit),
        "namespace_bridge": namespace_mode,
        "documented_full_discovery_command": (
            ["python", "-B", "-m", "unittest", "discover", "-v", "-s", "tests", "-t", "."]
            if module == "full" else None
        ),
        "tests": result.testsRun,
        "seconds": round(time.monotonic() - started, 3),
        "failures": [{"id": test.id(), "traceback": detail} for test, detail in result.failures],
        "errors": [{"id": test.id(), "traceback": detail} for test, detail in result.errors],
        "skipped": [{"id": test.id(), "reason": reason} for test, reason in result.skipped],
        "forbidden_process_attempts": attempts,
    }
    destination.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() and not attempts else 1


def invoke(
    module: str,
    destination: Path,
    timeout: int,
    target_root: Path = ROOT,
    baseline_namespace: bool = False,
    source_commit: str | None = None,
    driver_commit: str | None = None,
) -> dict:
    target_root = target_root.resolve()
    source_commit = source_commit or (os.environ.get("GITHUB_SHA") if target_root == ROOT else None)
    driver_commit = driver_commit or os.environ.get("TICKET24_DRIVER_COMMIT") or os.environ.get("GITHUB_SHA")
    command = [
        sys.executable, "-B", str(Path(__file__).resolve()), str(destination), "--child", module,
        "--target-root", str(target_root),
    ]
    if baseline_namespace:
        command.append("--baseline-namespace")
    if source_commit:
        command.extend(["--source-commit", source_commit])
    if driver_commit:
        command.extend(["--driver-commit", driver_commit])
    exit_code = None
    try:
        completed = subprocess.run(command, cwd=target_root, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True,
                                   encoding="utf-8", errors="replace", timeout=timeout)
        output = completed.stdout
        exit_code = completed.returncode
        problem = f"exit {completed.returncode} without a receipt"
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        problem = f"timeout after {timeout} seconds"
    receipt_provenance = provenance(target_root, source_commit, driver_commit)
    destination.with_suffix(".log").write_text(output, encoding="utf-8")
    destination.with_suffix(".process.json").write_text(
        json.dumps({
            "exit_code": exit_code,
            "timeout_seconds": timeout,
            "timed_out": exit_code is None,
            "provenance": receipt_provenance,
        }, indent=2),
        encoding="utf-8",
    )
    if destination.is_file():
        receipt = json.loads(destination.read_text(encoding="utf-8"))
        if exit_code is None or (
            exit_code != 0 and not receipt["failures"] and not receipt["errors"]
            and not receipt["forbidden_process_attempts"]
        ):
            receipt["errors"].append({"id": module, "traceback": problem})
    else:
        receipt = {
            "module": module,
            "source_file": module_source(module, target_root),
            "source_commit": source_commit,
            "provenance": receipt_provenance,
            "namespace_bridge": (
                "not_used_for_full_discovery" if module == "full"
                else "requested_for_per_module_imports" if baseline_namespace
                else "disabled"
            ),
            "documented_full_discovery_command": (
                ["python", "-B", "-m", "unittest", "discover", "-v", "-s", "tests", "-t", "."]
                if module == "full" else None
            ),
            "tests": 0,
            "seconds": None,
            "failures": [],
            "errors": [{"id": module, "traceback": problem}],
            "skipped": [],
            "forbidden_process_attempts": [],
        }
        destination.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"{module}: {receipt['tests']} tests; {len(receipt['failures'])} FAIL, "
          f"{len(receipt['errors'])} ERROR, {len(receipt['skipped'])} skipped", flush=True)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--child")
    parser.add_argument("--target-root", type=Path, default=ROOT)
    parser.add_argument("--baseline-namespace", action="store_true")
    parser.add_argument("--source-commit")
    parser.add_argument("--driver-commit")
    args = parser.parse_args()
    target_root = args.target_root.resolve()
    source_commit = args.source_commit
    if source_commit is None and target_root == ROOT:
        source_commit = os.environ.get("GITHUB_SHA")
    driver_commit = args.driver_commit or os.environ.get("TICKET24_DRIVER_COMMIT") or os.environ.get("GITHUB_SHA")
    if args.child:
        return child(
            args.child, args.output, target_root, args.baseline_namespace,
            source_commit, driver_commit,
        )

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    modules_directory = output / "modules"
    modules_directory.mkdir()
    # Supervisor-only diagnostics use the driver's helper. Baseline test imports
    # happen in fresh children and must not require this newly added module.
    sys.path.insert(0, str(ROOT))
    from safe_action_core.path_safety import require_no_untrusted_symlinks

    system_temp = Path(tempfile.gettempdir())
    receipt_provenance = provenance(target_root, source_commit, driver_commit)
    modules = [f"tests.{path.stem}" for path in sorted((target_root / "tests").glob("test_*.py"))]
    metadata = {
        "commit": source_commit,
        "source_commit": source_commit,
        "target_root": str(target_root),
        "module_inventory_root": str(target_root / "tests"),
        "module_inventory_count": len(modules),
        "per_module_timeout_seconds": 900,
        "workers": 1,
        "namespace_bridge": "per_module_only" if args.baseline_namespace else "disabled",
        "documented_full_discovery_command": [
            "python", "-B", "-m", "unittest", "discover", "-v", "-s", "tests", "-t", ".",
        ],
        "provenance": receipt_provenance,
        "python": sys.version,
        "system": platform.system(),
        "release": platform.release(),
        "system_temp": str(system_temp),
        "validated_system_temp": str(require_no_untrusted_symlinks(system_temp)),
        "system_temp_validator_source": "driver:safe_action_core.path_safety",
    }
    (output / "environment.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    started = time.monotonic()
    # Keep the collector itself from adding CPU contention to bounded native OCR.
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = [
            executor.submit(
                invoke, module, modules_directory / f"{module}.json", 900,
                target_root, args.baseline_namespace, source_commit, driver_commit,
            )
            for module in modules
        ]
        results = [future.result() for future in as_completed(futures)]
    elapsed = round(time.monotonic() - started, 3)
    results.sort(key=lambda row: row["module"])
    summary = {"environment": metadata, "seconds": elapsed, "modules": results}
    (output / "per-module.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    full = invoke(
        "full", output / "full.json", 7200, target_root,
        args.baseline_namespace, source_commit, driver_commit,
    )
    (output / "full-execution.json").write_text(json.dumps(full, indent=2), encoding="utf-8")
    print(json.dumps({"modules": len(results), "tests": sum(row["tests"] for row in results),
                      "per_module_seconds": elapsed, "full_seconds": full["seconds"]}), flush=True)
    return 1 if any(row["failures"] or row["errors"] or row["forbidden_process_attempts"]
                    for row in [*results, full]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
