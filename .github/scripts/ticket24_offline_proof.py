"""Ticket #24 diagnostic receipts; the required gate is full unittest discovery."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = {"adb", "hd-adb", "ssh", "scp", "plink", "hd-player", "bluestacks", "scrcpy", "vboxmanage", "vmrun", "virsh"}


def child(module: str, destination: Path) -> int:
    sys.path.insert(0, str(ROOT))
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
        "tests": result.testsRun,
        "seconds": round(time.monotonic() - started, 3),
        "failures": [{"id": test.id(), "traceback": detail} for test, detail in result.failures],
        "errors": [{"id": test.id(), "traceback": detail} for test, detail in result.errors],
        "skipped": [{"id": test.id(), "reason": reason} for test, reason in result.skipped],
        "forbidden_process_attempts": attempts,
    }
    destination.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() and not attempts else 1


def invoke(module: str, destination: Path, timeout: int) -> dict:
    command = [sys.executable, "-B", str(Path(__file__).resolve()), str(destination), "--child", module]
    exit_code = None
    try:
        completed = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
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
    destination.with_suffix(".log").write_text(output, encoding="utf-8")
    destination.with_suffix(".process.json").write_text(
        json.dumps({"exit_code": exit_code, "timeout_seconds": timeout}, indent=2),
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
        receipt = {"module": module, "tests": 0, "seconds": None,
                   "failures": [], "errors": [{"id": module, "traceback": problem}],
                   "skipped": [], "forbidden_process_attempts": []}
        destination.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"{module}: {receipt['tests']} tests; {len(receipt['failures'])} FAIL, "
          f"{len(receipt['errors'])} ERROR, {len(receipt['skipped'])} skipped", flush=True)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--child")
    args = parser.parse_args()
    if args.child:
        return child(args.child, args.output)

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    modules_directory = output / "modules"
    modules_directory.mkdir()
    sys.path.insert(0, str(ROOT))
    from safe_action_core.path_safety import require_no_untrusted_symlinks

    system_temp = Path(tempfile.gettempdir())
    metadata = {
        "commit": os.environ.get("GITHUB_SHA"),
        "python": sys.version,
        "system": platform.system(),
        "release": platform.release(),
        "system_temp": str(system_temp),
        "validated_system_temp": str(require_no_untrusted_symlinks(system_temp)),
        "per_module_timeout_seconds": 900,
        "workers": 4,
    }
    (output / "environment.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    modules = [f"tests.{path.stem}" for path in sorted((ROOT / "tests").glob("test_*.py"))]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(invoke, module, modules_directory / f"{module}.json", 900)
                   for module in modules]
        results = [future.result() for future in as_completed(futures)]
    elapsed = round(time.monotonic() - started, 3)
    results.sort(key=lambda row: row["module"])
    summary = {"environment": metadata, "seconds": elapsed, "modules": results}
    (output / "per-module.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    full = invoke("full", output / "full.json", 7200)
    (output / "full-execution.json").write_text(json.dumps(full, indent=2), encoding="utf-8")
    print(json.dumps({"modules": len(results), "tests": sum(row["tests"] for row in results),
                      "per_module_seconds": elapsed, "full_seconds": full["seconds"]}), flush=True)
    return 1 if any(row["failures"] or row["errors"] or row["forbidden_process_attempts"]
                    for row in [*results, full]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
