"""Bounded first-contact readiness for private local BlueStacks ADB.

This module intentionally has no project imports.  Both the operator wrapper and
the child runtime can use the same contract without creating an import cycle.
It starts the fixed local ADB server once per process/key, then polls the
configured serial until it reports ``device``.  It never runs ``adb connect``.
"""

from __future__ import annotations

from collections.abc import Callable, MutableSet, Sequence
import subprocess
import time
from typing import Any


class ADBReadinessError(RuntimeError):
    """The fixed local ADB endpoint did not become ready in bounded time."""


_READY: set[tuple[str, str]] = set()
_DEFAULT_BACKOFF = (0.05, 0.10, 0.20, 0.40, 0.80)
_DIAGNOSTIC_LIMIT = 180


def reset_adb_readiness_cache() -> None:
    """Clear process-local readiness state (primarily for tests)."""

    _READY.clear()


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value or "")


def _bounded(value: str) -> str:
    value = " ".join(value.split())
    return value[:_DIAGNOSTIC_LIMIT]


def _diagnostic(result: Any) -> str:
    stderr = _bounded(_text(getattr(result, "stderr", "")))
    stdout = _bounded(_text(getattr(result, "stdout", "")))
    state = stdout or stderr or f"returncode={getattr(result, 'returncode', '?')}"
    return _bounded(state)


def ensure_adb_ready(
    executable: str,
    serial: str | None,
    *,
    run: Callable[..., Any] | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    deadline_seconds: float = 8.0,
    command_timeout_seconds: float = 5.0,
    backoff: Sequence[float] = _DEFAULT_BACKOFF,
    cache: MutableSet[tuple[str, str]] | None = None,
) -> None:
    """Ensure one private serial is ready, with bounded first-contact retry.

    ``run``, ``monotonic``, ``sleep``, and ``cache`` are injectable so tests can
    prove ordering and timeout behavior without touching a real emulator.
    """

    if not executable:
        raise ADBReadinessError("ADB readiness requires an executable")
    if deadline_seconds <= 0 or command_timeout_seconds <= 0:
        raise ADBReadinessError("ADB readiness bounds must be positive")
    runner = run or subprocess.run
    clock = monotonic or time.monotonic
    sleeper = sleep or time.sleep
    ready_cache = cache if cache is not None else _READY
    # A serial-less call is used only for `devices -l` discovery.  It starts
    # the fixed server but intentionally does not probe or connect any target.
    key = (str(executable), str(serial) if serial is not None else "<devices>")
    if key in ready_cache:
        return

    started = clock()
    deadline = started + deadline_seconds
    start_context = ""
    server = None
    # Starting the approved server is deliberately unqualified: no serial and
    # no network connect are permitted on this path.
    try:
        server = runner(
            [str(executable), "start-server"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=min(command_timeout_seconds, deadline_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired:
        if serial is None:
            raise ADBReadinessError("ADB readiness failed: start-server timed out") from None
        start_context = "start-server timed out; "
    except OSError as exc:
        raise ADBReadinessError(
            f"ADB readiness failed: start-server unavailable ({_bounded(str(exc))})"
        ) from exc
    if server is not None and getattr(server, "returncode", 1):
        detail = _diagnostic(server)
        raise ADBReadinessError(
            "ADB readiness failed: start-server returned "
            f"{getattr(server, 'returncode', '?')} ({detail})"
        )

    if serial is None:
        ready_cache.add(key)
        return

    attempts = 0
    last_detail = "no probe result"
    backoff_values = tuple(max(0.0, float(value)) for value in backoff)
    # The attempt cap protects injected/static clocks while the monotonic
    # deadline remains the production bound.
    max_attempts = max(1, len(backoff_values) + 3)
    while attempts < max_attempts:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        attempts += 1
        try:
            probe = runner(
                [str(executable), "-s", str(serial), "get-state"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=min(command_timeout_seconds, max(0.01, remaining)),
                check=False,
            )
            state = _text(getattr(probe, "stdout", "")).strip()
            last_detail = _diagnostic(probe)
            if getattr(probe, "returncode", 1) == 0 and state == "device":
                ready_cache.add(key)
                return
        except subprocess.TimeoutExpired:
            last_detail = "probe timed out"
        except OSError as exc:
            last_detail = _bounded(str(exc))

        remaining = deadline - clock()
        if remaining <= 0:
            break
        delay = backoff_values[min(attempts - 1, len(backoff_values) - 1)] if backoff_values else 0.0
        sleeper(min(delay, remaining))

    raise ADBReadinessError(
        "ADB readiness timed out for private serial "
        f"{serial}: attempts={attempts}, last={_bounded(start_context + last_detail)}"
    )
