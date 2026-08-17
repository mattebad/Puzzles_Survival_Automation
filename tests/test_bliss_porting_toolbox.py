from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.bliss_porting.remote import (
    PortingConfig,
    PortingError,
    redact_argv,
    run_remote,
    worker_start,
)


ROOT = Path(__file__).resolve().parents[1]


def config(root: Path, **changes: str) -> PortingConfig:
    values = {
        "repo_root": root,
        "host": "private-host",
        "host_key": "ssh-ed25519 255 fingerprint",
        "serial": "private-guest:5555",
        "container": "future-port",
        "image": "future-port:manual",
        "remote_workspace": "/mnt/cache/future-port",
        "remote_evidence": "/mnt/cache/future-port-evidence",
        "adb_socket": "tcp:127.0.0.1:5042",
        "adb_host_path": "/usr/local/bin/adb",
        "plink": "C:/tools/plink.exe",
        "pscp": "C:/tools/pscp.exe",
    }
    values.update(changes)
    return PortingConfig(**values)


class BlissPortingToolboxTests(unittest.TestCase):
    def test_private_adb_and_explicit_targets_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(PortingError, "private loopback"):
                config(root, adb_socket="tcp:0.0.0.0:5042")
            with self.assertRaisesRegex(PortingError, "explicitly provided"):
                config(root, host="")

    def test_credentials_are_process_only_and_redacted(self) -> None:
        recorded: list[list[str]] = []

        def runner(argv, **_kwargs):
            recorded.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "UNRAID_TEMP_USERNAME": "temporary-user",
                "UNRAID_TEMP_PASSWORD": "temporary-password",
            },
            clear=False,
        ):
            output = run_remote(config(Path(directory)), "true", runner=runner)

        self.assertEqual(output, "ok\n")
        self.assertIn("temporary-password", recorded[0])
        self.assertNotIn("temporary-password", redact_argv(recorded[0]))

    def test_worker_is_constrained_and_publishes_no_port(self) -> None:
        commands: list[str] = []

        def runner(argv, **_kwargs):
            commands.append(str(argv[-1]))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "UNRAID_TEMP_USERNAME": "temporary-user",
                "UNRAID_TEMP_PASSWORD": "temporary-password",
            },
            clear=False,
        ):
            worker_start(config(Path(directory)), runner=runner)

        command = commands[0]
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop ALL", command)
        self.assertIn("--security-opt no-new-privileges", command)
        docker_run = command.split("docker run", 1)[1]
        self.assertNotIn(" -p ", docker_run)
        self.assertNotIn("--publish", docker_run)

    def test_active_pnsctl_has_no_porting_import_or_remote_defaults(self) -> None:
        source = (ROOT / "scripts" / "pnsctl.py").read_text(encoding="utf-8")
        for forbidden in (
            "scripts.bliss_porting",
            "nas.local",
            "192.168.122.79:5555",
            "mvp_quest_to_claim",
            "MVP-QUEST-TO-CLAIM",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
