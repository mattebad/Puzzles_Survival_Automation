"""Host-neutral remote primitives for a future Bliss port.

This module deliberately contains transport and worker mechanics only.  It has
no active-game imports, flow identifiers, screen geometry, task names, or
runtime defaults.  The CLI is manual-only; callers must provide every target
and command-specific value.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import time
from shlex import quote
from typing import Callable, Iterable, Mapping, Sequence


CommandRunner = Callable[..., subprocess.CompletedProcess]
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PRIVATE_ADB_SOCKET_RE = re.compile(r"^tcp:127\.0\.0\.1:[0-9]+$")


class PortingError(RuntimeError):
    """Raised when an explicit manual-porting request is invalid or fails."""


@dataclass(frozen=True)
class PortingConfig:
    """All remote target details required for one manual operation."""

    repo_root: Path
    host: str
    host_key: str
    serial: str
    container: str
    image: str
    remote_workspace: str
    remote_evidence: str
    adb_socket: str
    adb_host_path: str
    plink: str
    pscp: str

    def __post_init__(self) -> None:
        for label in (
            "host",
            "host_key",
            "serial",
            "container",
            "image",
            "remote_workspace",
            "remote_evidence",
            "adb_socket",
            "adb_host_path",
            "plink",
            "pscp",
        ):
            value = getattr(self, label)
            if type(value) is not str or not value.strip():
                raise PortingError(f"{label} must be explicitly provided")
        if any(character.isspace() for character in self.host):
            raise PortingError("host must not contain whitespace")
        if not PRIVATE_ADB_SOCKET_RE.fullmatch(self.adb_socket):
            raise PortingError(
                "adb_socket must bind a private loopback TCP endpoint"
            )
        if not NAME_RE.fullmatch(self.container):
            raise PortingError(
                "container must contain only letters, numbers, dot, dash, or underscore"
            )


def load_credentials(
    env_path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Load temporary credentials for one subprocess invocation.

    The normal source is the process environment.  An explicit path is
    supported for compatibility with a manually selected local porting
    session; values are read into memory and are never returned in command
    output or serialized by this module.
    """

    values: dict[str, str] = {}
    if env_path is not None:
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise PortingError("credential source could not be read") from exc
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name in {"UNRAID_TEMP_USERNAME", "UNRAID_TEMP_PASSWORD"}:
                values[name] = value.strip().strip('"').strip("'")
    source = os.environ if environ is None else environ
    values.setdefault("UNRAID_TEMP_USERNAME", source.get("UNRAID_TEMP_USERNAME", ""))
    values.setdefault("UNRAID_TEMP_PASSWORD", source.get("UNRAID_TEMP_PASSWORD", ""))
    if not values["UNRAID_TEMP_USERNAME"] or not values["UNRAID_TEMP_PASSWORD"]:
        raise PortingError(
            "temporary remote credentials must be supplied by the process environment"
        )
    return values["UNRAID_TEMP_USERNAME"], values["UNRAID_TEMP_PASSWORD"]


def redact_argv(argv: Sequence[str]) -> list[str]:
    """Return an argv copy with process-only password arguments redacted."""

    result = list(argv)
    for index, item in enumerate(result[:-1]):
        if item == "-pw":
            result[index + 1] = "<process-only-password>"
    return result


def _plink_argv(
    config: PortingConfig,
    command: str,
    *,
    credentials: tuple[str, str] | None = None,
) -> list[str]:
    if type(command) is not str or not command.strip():
        raise PortingError("remote command must be explicitly provided")
    username, password = credentials or load_credentials()
    return [
        config.plink,
        "-batch",
        "-hostkey",
        config.host_key,
        "-pw",
        password,
        f"{username}@{config.host}",
        command,
    ]


def _pscp_argv(
    config: PortingConfig,
    sources: Iterable[str],
    destination: str,
    recursive: bool = False,
    *,
    local_sources: bool = True,
    local_destination: bool = False,
    credentials: tuple[str, str] | None = None,
) -> list[str]:
    source_list = list(sources)
    if not source_list or any(type(source) is not str or not source for source in source_list):
        raise PortingError("at least one explicit PSCP source is required")
    if type(destination) is not str or not destination:
        raise PortingError("PSCP destination must be explicitly provided")
    username, password = credentials or load_credentials()
    args = [
        config.pscp,
        "-batch",
        "-hostkey",
        config.host_key,
        "-pw",
        password,
    ]
    if recursive:
        args.append("-r")
    args.extend(
        _windows_path(source) if local_sources else f"{username}@{config.host}:{source}"
        for source in source_list
    )
    if local_destination:
        args.append(_windows_path(destination))
    else:
        args.append(f"{username}@{config.host}:{destination}")
    return args


def _run(
    argv: Sequence[str],
    *,
    runner: CommandRunner = subprocess.run,
    failure: str,
) -> subprocess.CompletedProcess:
    result = runner(argv, check=False, capture_output=True, text=True)
    if result.returncode:
        detail = "\n".join(
            part
            for part in (str(result.stdout).strip(), str(result.stderr).strip())
            if part
        )
        raise PortingError(f"{failure}: {detail}".rstrip())
    return result


def run_remote(
    config: PortingConfig,
    command: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> str:
    """Run one explicit command on the selected remote host."""

    credentials = load_credentials()
    result = _run(
        _plink_argv(config, command, credentials=credentials),
        runner=runner,
        failure="remote command failed",
    )
    return str(result.stdout)


def _windows_path(value: str) -> str:
    if value.startswith("/mnt/") and len(value) > 6:
        drive = value[5].upper()
        return drive + ":/" + value[7:]
    return value


def run_pscp(
    config: PortingConfig,
    sources: Iterable[str],
    destination: str,
    recursive: bool = False,
    *,
    local_sources: bool = True,
    local_destination: bool = False,
    runner: CommandRunner = subprocess.run,
) -> None:
    """Copy explicit local or remote paths without retaining credentials."""

    credentials = load_credentials()
    _run(
        _pscp_argv(
            config,
            sources,
            destination,
            recursive,
            local_sources=local_sources,
            local_destination=local_destination,
            credentials=credentials,
        ),
        runner=runner,
        failure="remote copy failed",
    )


def _safe_name(value: str) -> str:
    if type(value) is not str or not NAME_RE.fullmatch(value):
        raise PortingError(
            "artifact name must contain only letters, numbers, dot, dash, or underscore"
        )
    return value


def sync_workspace(
    config: PortingConfig,
    sources: Iterable[str],
    remote_destination: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> None:
    """Synchronize only the caller-selected paths into a remote workspace."""

    source_list = list(sources)
    if not source_list:
        raise PortingError("workspace synchronization requires explicit sources")
    if type(remote_destination) is not str or not remote_destination:
        raise PortingError("workspace destination must be explicitly provided")
    run_remote(
        config,
        f"mkdir -p {quote(remote_destination)}",
        runner=runner,
    )
    run_pscp(
        config,
        source_list,
        remote_destination,
        recursive=True,
        runner=runner,
    )


def build_image(
    config: PortingConfig,
    dockerfile: str,
    build_context: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> str:
    """Build a caller-selected image on the remote host."""

    if type(dockerfile) is not str or not dockerfile.strip():
        raise PortingError("dockerfile must be explicitly provided")
    if type(build_context) is not str or not build_context.strip():
        raise PortingError("build context must be explicitly provided")
    command = (
        f"docker build --file {quote(dockerfile)} "
        f"--tag {quote(config.image)} {quote(build_context)}"
    )
    return run_remote(config, command, runner=runner)


def _adb_shell_command(config: PortingConfig, command: str) -> str:
    if type(command) is not str or not command.strip():
        raise PortingError("ADB command must be explicitly provided")
    adb_port = config.adb_socket.rsplit(":", 1)[1]
    script = (
        "set -eu; "
        'if test -x /opt/adb; then adb_bin=/opt/adb; '
        "else adb_bin=$(command -v adb); fi; "
        f"export HOME=/tmp; export ADB_SERVER_PORT={adb_port}; "
        "unset ADB_SERVER_SOCKET; "
        f'exec "$adb_bin" -s {quote(config.serial)} {command}'
    )
    return (
        f"docker exec -e ADB_SERVER_SOCKET={quote(config.adb_socket)} "
        f"{quote(config.container)} sh -lc {quote(script)}"
    )


def adb_start(
    config: PortingConfig,
    *,
    runner: CommandRunner = subprocess.run,
) -> str:
    """Start the private in-container ADB server and bind the explicit serial."""

    adb_port = config.adb_socket.rsplit(":", 1)[1]
    command = (
        f"docker exec -e ADB_SERVER_SOCKET={quote(config.adb_socket)} "
        f"{quote(config.container)} sh -lc "
        + quote(
            "set -eu; "
            'if test -x /opt/adb; then adb_bin=/opt/adb; '
            "else adb_bin=$(command -v adb); fi; "
            f"export HOME=/tmp; export ADB_SERVER_PORT={adb_port}; "
            'unset ADB_SERVER_SOCKET; "$adb_bin" start-server; '
            f'"$adb_bin" -s {quote(config.serial)} connect {quote(config.serial)}; '
            '"$adb_bin" devices'
        )
    )
    return run_remote(config, command, runner=runner)


def launch(
    config: PortingConfig,
    activity: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> str:
    """Launch an explicitly supplied Android activity in the future port."""

    if type(activity) is not str or not activity.strip() or any(
        character.isspace() for character in activity
    ):
        raise PortingError("activity must be explicitly provided without whitespace")
    return run_remote(
        config,
        _adb_shell_command(config, f"shell am start -W -n {quote(activity)}"),
        runner=runner,
    )


def capture(
    config: PortingConfig,
    name: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> str:
    """Capture one explicitly named native frame into remote evidence storage."""

    safe_name = _safe_name(name)
    remote_path = f"{config.remote_evidence}/{safe_name}.png"
    return run_remote(
        config,
        f"{_adb_shell_command(config, 'exec-out screencap -p')} > {quote(remote_path)}",
        runner=runner,
    )


def observe(
    config: PortingConfig,
    name: str,
    *,
    runner: CommandRunner = subprocess.run,
    clock: Callable[[], float] = time.time,
) -> str:
    """Capture a frame and report raw foreground diagnostics."""

    capture_started = clock()
    capture(config, name, runner=runner)
    capture_completed = clock()
    foreground = run_remote(
        config,
        _adb_shell_command(config, "shell dumpsys window"),
        runner=runner,
    )
    return json.dumps(
        {
            "capture": _safe_name(name),
            "capture_started_epoch": capture_started,
            "capture_completed_epoch": capture_completed,
            "capture_completed_utc": datetime.fromtimestamp(
                capture_completed, timezone.utc
            ).isoformat(),
            "foreground": foreground.strip(),
        },
        sort_keys=True,
    )


def worker_start(
    config: PortingConfig,
    *,
    runner: CommandRunner = subprocess.run,
) -> str:
    """Create a constrained worker with no published host ports."""

    command = f"""
set -eu
mkdir -p {quote(config.remote_evidence)}
if docker inspect {quote(config.container)} >/dev/null 2>&1; then
  docker ps --filter name=^{re.escape(config.container)}$ --format '{{{{.Names}}}} {{{{.Status}}}}'
  exit 0
fi
adb_mount=''
if test -x {quote(config.adb_host_path)}; then
  adb_mount='-v {quote(config.adb_host_path)}:/opt/adb:ro'
fi
docker run -d --name {quote(config.container)} --network host --user 65534:65534 --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m --pids-limit 256 --memory 2g --cpus 2 \
  --cap-drop ALL --security-opt no-new-privileges \
  -v {quote(config.remote_workspace)}:/workspace:ro \
  -v {quote(config.remote_evidence)}:/evidence:rw \
  $adb_mount -w /workspace {quote(config.image)} sh -lc 'exec tail -f /dev/null'
"""
    return run_remote(config, command, runner=runner)


def worker_status(
    config: PortingConfig,
    *,
    runner: CommandRunner = subprocess.run,
) -> str:
    return run_remote(
        config,
        f"docker ps -a --filter name=^{re.escape(config.container)}$ "
        "--format '{{.Names}} {{.Status}}'",
        runner=runner,
    )


def worker_stop(
    config: PortingConfig,
    *,
    runner: CommandRunner = subprocess.run,
) -> str:
    return run_remote(
        config,
        f"docker rm -f {quote(config.container)} 2>/dev/null || true",
        runner=runner,
    )


def worker_exec(
    config: PortingConfig,
    command: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> str:
    """Run one explicit command inside the selected worker."""

    if type(command) is not str or not command.strip():
        raise PortingError("worker command must be explicitly provided")
    adb_port = config.adb_socket.rsplit(":", 1)[1]
    docker_command = (
        f"docker exec -e HOME=/tmp -e ADB_SERVER_PORT={adb_port} "
        f"-w /workspace {quote(config.container)} sh -lc {quote(command)}"
    )
    return run_remote(config, docker_command, runner=runner)


__all__ = [
    "PortingConfig",
    "PortingError",
    "adb_start",
    "build_image",
    "capture",
    "launch",
    "load_credentials",
    "observe",
    "redact_argv",
    "run_pscp",
    "run_remote",
    "sync_workspace",
    "worker_exec",
    "worker_start",
    "worker_status",
    "worker_stop",
]
