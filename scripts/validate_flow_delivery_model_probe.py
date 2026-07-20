#!/usr/bin/env python3
"""Validate runtime routing events for the four PnS custom subagents."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = ROOT / ".local-orchestrator"
EVENTS = LOCAL_ROOT / "model-routing-events.jsonl"
REPORT = LOCAL_ROOT / "model-routing-probe-report.json"
EXPECTED_MODEL = "cursor-grok-4.5-high"
PARENT_MODEL = "gpt-5.6-sol-high"
AGENTS = (
    "pns-flow-recon",
    "pns-flow-implementer",
    "pns-flow-reviewer",
    "pns-evidence-reviewer",
)


def _agent_command() -> list[str]:
    if os.name == "nt":
        powershell = (
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        launcher = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "cursor-agent"
            / "cursor-agent.ps1"
        )
        if powershell.is_file() and launcher.is_file():
            return [
                str(powershell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(launcher),
            ]
    executable = shutil.which("agent")
    if not executable:
        raise RuntimeError("authenticated Cursor Agent CLI is unavailable")
    return [executable]


def _git_tree_state() -> bytes:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def run_probe() -> tuple[list[dict[str, object]], dict[str, object]]:
    command = _agent_command()
    catalog = subprocess.run(
        [*command, "models"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    if PARENT_MODEL not in catalog or EXPECTED_MODEL not in catalog:
        raise RuntimeError("installed Cursor model catalog lacks a required pinned model")
    prompt = (
        "Controlled routing probe only. Invoke each project custom subagent serially by exact "
        "name: pns-flow-recon, pns-flow-implementer, pns-flow-reviewer, and "
        "pns-evidence-reviewer. Give each the same harmless read-only task: return exactly the "
        "first Markdown heading of AGENTS.md. The implementer must not edit anything. Do not use "
        "a built-in subagent, edit files, run tests, or issue runtime input."
    )
    before = _git_tree_state()
    completed = subprocess.run(
        [
            *command,
            "-p",
            "--trust",
            "--model",
            PARENT_MODEL,
            "--output-format",
            "stream-json",
            prompt,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    after = _git_tree_state()
    if after != before:
        raise RuntimeError("model-routing probe changed the Git working tree")
    if completed.returncode:
        raise RuntimeError(
            "Cursor Agent routing probe failed: "
            + (completed.stderr or completed.stdout)[-1000:]
        )
    parent_runtime_model: str | None = None
    events: list[dict[str, object]] = []
    completed_agents: set[str] = set()
    unexpected_subagents: list[object] = []
    for line in completed.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") == "system" and item.get("subtype") == "init":
            parent_runtime_model = item.get("model")
        if item.get("type") != "tool_call":
            continue
        task_call = item.get("tool_call", {}).get("taskToolCall", {})
        args = task_call.get("args", {})
        custom = args.get("subagentType", {}).get("custom", {})
        name = custom.get("name") if isinstance(custom, dict) else None
        if item.get("subtype") == "started":
            if name not in AGENTS:
                unexpected_subagents.append(args.get("subagentType"))
                continue
            events.append(
                {
                    "subagent_type": name,
                    "subagent_model": args.get("model"),
                    "subagent_id": args.get("agentId"),
                    "model_params": None,
                    "cursor_version": None,
                }
            )
        elif item.get("subtype") == "completed" and name in AGENTS:
            result = task_call.get("result", {})
            if isinstance(result, dict) and "success" in result:
                completed_agents.add(name)
    if unexpected_subagents:
        raise RuntimeError(
            f"routing probe invoked non-allowlisted subagents: {unexpected_subagents}"
        )
    counts = {name: sum(event["subagent_type"] == name for event in events) for name in AGENTS}
    if any(count != 1 for count in counts.values()):
        raise RuntimeError(f"routing probe did not invoke each custom subagent exactly once: {counts}")
    if set(AGENTS) != completed_agents:
        missing = sorted(set(AGENTS) - completed_agents)
        raise RuntimeError(f"custom subagent probe did not complete: {missing}")
    metadata = {
        "source": "cursor_agent_stream_json",
        "parent_configured_model": PARENT_MODEL,
        "parent_runtime_model": parent_runtime_model,
        "model_catalog_validated": True,
    }
    return events, metadata


def frontmatter_model(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^model:\s*(\S+)\s*$", text)
    return match.group(1) if match else None


def atomic_report(payload: dict[str, object]) -> None:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".model-routing-probe-report.",
        suffix=".tmp",
        dir=LOCAL_ROOT,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, REPORT)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help="invoke all four custom agents and validate stream metadata",
    )
    args = parser.parse_args(argv)
    configured = {
        name: frontmatter_model(ROOT / ".cursor" / "agents" / f"{name}.md")
        for name in AGENTS
    }
    events: list[dict[str, object]] = []
    metadata: dict[str, object] = {"source": "subagent_start_hook"}
    try:
        if args.run:
            events, metadata = run_probe()
        else:
            for line in EVENTS.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if isinstance(item, dict):
                        events.append(item)
    except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError, subprocess.SubprocessError) as exc:
        metadata = {"source": "probe_error", "error": str(exc)}
        events = []
    latest = {
        name: next(
            (event for event in reversed(events) if event.get("subagent_type") == name),
            None,
        )
        for name in AGENTS
    }
    checks: dict[str, dict[str, object]] = {}
    passed = True
    for name in AGENTS:
        event = latest[name]
        runtime_model = event.get("subagent_model") if event else None
        runtime_params = event.get("model_params") if event else None
        configured_ok = configured[name] == EXPECTED_MODEL
        runtime_ok = runtime_model == EXPECTED_MODEL
        agent_passed = configured_ok and runtime_ok
        passed = passed and agent_passed
        checks[name] = {
            "configured_model": configured[name],
            "runtime_model": runtime_model,
            "runtime_model_params": runtime_params,
            "cursor_version": event.get("cursor_version") if event else None,
            "subagent_id": event.get("subagent_id") if event else None,
            "passed": agent_passed,
        }
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "expected_model": EXPECTED_MODEL,
        "parent_expected_model": PARENT_MODEL,
        "probe": metadata,
        "checks": checks,
        "passed": passed,
    }
    atomic_report(payload)
    print(json.dumps(payload, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
