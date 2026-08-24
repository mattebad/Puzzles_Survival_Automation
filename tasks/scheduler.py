"""Serializable task-state and narrow one-pulse scheduler contracts.

This is offline Phase F work.  It does not acquire a lease, dispatch input, or replace the SQLite
action journal.  The production integration must call this contract only after the existing safety
core has supplied lease and unresolved-action gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import math
from typing import Any, Iterable, Mapping, Optional, Protocol

from .contracts import TaskOutcome, TaskResult


STATE_SCHEMA = "phase-f-task-state-v1"


class TaskStateStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    BLOCKED = "blocked"
    UNRESOLVED = "unresolved"


class SchedulerError(ValueError):
    """Raised when a state snapshot or scheduler update is invalid."""


@dataclass(frozen=True)
class TaskState:
    task_id: str
    completion_key: str
    game_day_id: str
    status: TaskStateStatus = TaskStateStatus.PENDING
    next_due_monotonic: Optional[float] = 0.0
    revision: int = 0
    last_reason: str = ""

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.completion_key.strip() or not self.game_day_id.strip():
            raise SchedulerError("task state requires task, completion-key, and game-day identity")
        if self.next_due_monotonic is not None and not math.isfinite(self.next_due_monotonic):
            raise SchedulerError("next due time must be finite or None")
        if self.revision < 0:
            raise SchedulerError("task state revision cannot be negative")


@dataclass(frozen=True)
class PulseCandidate:
    task_id: str
    completion_key: str
    game_day_id: str
    due_at_monotonic: float


class TaskStateRepository(Protocol):
    def save(self, state: TaskState, updated_at: float) -> TaskState:
        ...

    def list(self) -> tuple[TaskState, ...]:
        ...


class LegacySchedulerRetiredError(SchedulerError):
    """The monotonic Phase-F scheduler is preserved only as historical state."""


class OnePulseScheduler:
    """Retired compatibility artifact; the UTC coordinator is authoritative."""

    def __init__(self, states: Iterable[TaskState] = ()) -> None:
        raise LegacySchedulerRetiredError(
            "OnePulseScheduler is retired; use automation_service.scheduler.UtcPulseCoordinator"
        )


class SQLiteBackedOnePulseScheduler:
    """Retired SQLite compatibility artifact; it never interprets task_state."""

    def __init__(self, repository: TaskStateRepository) -> None:
        raise LegacySchedulerRetiredError(
            "SQLiteBackedOnePulseScheduler is retired; use SQLiteSchedulerInvocationRepository"
        )
