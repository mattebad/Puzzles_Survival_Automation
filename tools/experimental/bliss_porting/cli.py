"""Manual-only CLI for an explicitly selected future Bliss port."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from typing import Sequence

from .remote import (
    PortingConfig,
    PortingError,
    adb_start,
    build_image,
    capture,
    launch,
    observe,
    run_pscp,
    run_remote,
    sync_workspace,
    worker_exec,
    worker_start,
    worker_status,
    worker_stop,
)


MANUAL_ONLY = True


def _add_target_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--host", required=True)
    parser.add_argument("--host-key", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--remote-workspace", required=True)
    parser.add_argument("--remote-evidence", required=True)
    parser.add_argument("--adb-socket", required=True)
    parser.add_argument("--adb-host-path", required=True)
    parser.add_argument("--plink", required=True)
    parser.add_argument("--pscp", required=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="bliss-porting",
        description=(
            "MANUAL-ONLY future-porting toolbox. "
            "No active runtime, scheduler, or gameplay flow is attached."
        ),
    )
    commands = root.add_subparsers(dest="command", required=True)

    remote = commands.add_parser("remote", help="run one explicit remote command")
    _add_target_arguments(remote)
    remote.add_argument("--command", dest="command_text", required=True)

    copy = commands.add_parser("copy", help="copy explicit paths with PSCP")
    _add_target_arguments(copy)
    copy.add_argument("--source", action="append", required=True)
    copy.add_argument("--destination", required=True)
    copy.add_argument("--recursive", action="store_true")

    sync = commands.add_parser("sync", help="sync explicit paths to a workspace")
    _add_target_arguments(sync)
    sync.add_argument("--source", action="append", required=True)
    sync.add_argument("--destination", required=True)

    build = commands.add_parser("build", help="build one explicit remote image")
    _add_target_arguments(build)
    build.add_argument("--dockerfile", required=True)
    build.add_argument("--context", required=True)

    for name, help_text in (
        ("worker-start", "start the selected constrained worker"),
        ("worker-status", "inspect the selected worker"),
        ("worker-stop", "stop the selected worker"),
        ("adb-start", "start private remote ADB"),
    ):
        command = commands.add_parser(name, help=help_text)
        _add_target_arguments(command)

    launch_command = commands.add_parser(
        "launch", help="launch one explicitly selected Android activity"
    )
    _add_target_arguments(launch_command)
    launch_command.add_argument("--activity", required=True)

    capture_command = commands.add_parser(
        "capture", help="capture one explicitly named native frame"
    )
    _add_target_arguments(capture_command)
    capture_command.add_argument("--name", required=True)

    observe_command = commands.add_parser(
        "observe", help="capture and report raw foreground diagnostics"
    )
    _add_target_arguments(observe_command)
    observe_command.add_argument("--name", required=True)

    execute = commands.add_parser(
        "worker-exec", help="run one explicit command inside the worker"
    )
    _add_target_arguments(execute)
    execute.add_argument("--command", dest="command_text", required=True)
    return root


def _config(args: argparse.Namespace) -> PortingConfig:
    return PortingConfig(
        repo_root=args.repo_root.resolve(),
        host=args.host,
        host_key=args.host_key,
        serial=args.serial,
        container=args.container,
        image=args.image,
        remote_workspace=args.remote_workspace,
        remote_evidence=args.remote_evidence,
        adb_socket=args.adb_socket,
        adb_host_path=args.adb_host_path,
        plink=args.plink,
        pscp=args.pscp,
    )


def _dispatch(args: argparse.Namespace) -> str | None:
    config = _config(args)
    if args.command == "remote":
        return run_remote(config, args.command_text)
    if args.command == "copy":
        run_pscp(
            config,
            args.source,
            args.destination,
            recursive=args.recursive,
        )
        return None
    if args.command == "sync":
        sync_workspace(config, args.source, args.destination)
        return None
    if args.command == "build":
        return build_image(config, args.dockerfile, args.context)
    if args.command == "worker-start":
        return worker_start(config)
    if args.command == "worker-status":
        return worker_status(config)
    if args.command == "worker-stop":
        return worker_stop(config)
    if args.command == "adb-start":
        return adb_start(config)
    if args.command == "launch":
        return launch(config, args.activity)
    if args.command == "capture":
        return capture(config, args.name)
    if args.command == "observe":
        return observe(config, args.name)
    if args.command == "worker-exec":
        return worker_exec(config, args.command_text)
    raise PortingError("unknown manual-only command")


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        output = _dispatch(args)
    except (OSError, PortingError, subprocess.SubprocessError) as exc:
        print(f"bliss-porting: {exc}", file=sys.stderr)
        return 2
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
