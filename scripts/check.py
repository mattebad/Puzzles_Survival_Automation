"""Run the small, deterministic, device-free developer check set."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys


# Keep this list explicit. The repository's full unittest suite remains available;
# this command is deliberately a fast offline smoke/regression set, not discovery.
OFFLINE_TEST_MODULES: tuple[str, ...] = (
    "tests.test_safe_action_core",
    "tests.test_input_capability_firewall",
    "tests.test_pre_dispatch_freshness",
    "tests.test_resource_effect_authority_store",
    "tests.test_resource_effect_authority_history",
    "tests.test_automation_service_adapters",
    "tests.test_automation_service_boundaries",
    "tests.test_automation_service_canonical_authority",
    "tests.test_automation_service_scheduler_canonical",
    "tests.test_automation_service_state",
    "tests.test_product_authority",
    "tests.test_transition_stability",
    "tests.test_native_frame_replay",
    "tests.test_runtime_trace_projection",
)

_RUNTIME_ENVIRONMENT_KEYS = (
    "ADB_SERVER_SOCKET",
    "ANDROID_HOME",
    "ANDROID_SERIAL",
    "ANDROID_SDK_ROOT",
    "AUTOMATION_SERVICE_STATE_PATH",
    "BLUESTACKS_SERIAL",
)


def _parser() -> argparse.ArgumentParser:
    selected = "\n".join(f"  - {module}" for module in OFFLINE_TEST_MODULES)
    return argparse.ArgumentParser(
        description=(
            "Run the fixed deterministic unittest set against checked-in fixtures. "
            "No test discovery, device runtime, or dependency installation is performed."
        ),
        epilog=f"Selected offline modules (not comprehensive coverage):\n{selected}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "unittest", "-v", *OFFLINE_TEST_MODULES]

    print("offline check scope (static; not comprehensive):", flush=True)
    for module in OFFLINE_TEST_MODULES:
        print(f"  {module}", flush=True)
    print(f"$ {shlex.join(command)}", flush=True)

    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "0"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONPATH"] = str(root)
    for key in _RUNTIME_ENVIRONMENT_KEYS:
        environment.pop(key, None)

    try:
        completed = subprocess.run(command, cwd=root, env=environment, check=False)
    except OSError as exc:
        print(f"offline check could not start unittest: {exc}", file=sys.stderr)
        return 1
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
