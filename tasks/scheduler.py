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


class OnePulseScheduler:
    """Select at most one due task after external safety gates have passed."""

    def __init__(self, states: Iterable[TaskState] = ()) -> None:
        self._states: dict[str, TaskState] = {}
        for state in states:
            self.register(state)

    def register(self, state: TaskState) -> None:
        current = self._states.get(state.task_id)
        if current is not None and current.completion_key != state.completion_key:
            raise SchedulerError("task completion key cannot change")
        self._states[state.task_id] = state

    def snapshot(self) -> tuple[TaskState, ...]:
        return tuple(self._states[key] for key in sorted(self._states))

    def next_pulse(
        self,
        now_monotonic: float,
        game_day_id: str,
        *,
        lease_valid: bool,
        unresolved_action: bool,
    ) -> Optional[PulseCandidate]:
        """Return one deterministic candidate, or none when any global gate is closed."""

        if not math.isfinite(now_monotonic) or not game_day_id.strip():
            raise SchedulerError("scheduler time and game-day identity are required")
        if not lease_valid or unresolved_action:
            return None
        due = [
            state
            for state in self._states.values()
            if state.status == TaskStateStatus.PENDING
            and state.game_day_id == game_day_id
            and state.next_due_monotonic is not None
            and state.next_due_monotonic <= now_monotonic
        ]
        if not due:
            return None
        state = min(due, key=lambda item: (item.next_due_monotonic, item.task_id))
        return PulseCandidate(state.task_id, state.completion_key, state.game_day_id, state.next_due_monotonic)

    def record_result(
        self,
        task_id: str,
        result: TaskResult,
        now_monotonic: float,
        *,
        backoff_seconds: float = 60.0,
    ) -> TaskState:
        """Persist one task result without ever converting an unverified DONE into completion."""

        state = self._states.get(task_id)
        if state is None:
            raise SchedulerError("unknown task")
        if not math.isfinite(now_monotonic) or backoff_seconds <= 0 or not math.isfinite(backoff_seconds):
            raise SchedulerError("result time and positive finite backoff are required")
        if result.outcome == TaskOutcome.DONE:
            if not result.verified or result.completion_key != state.completion_key:
                updated = TaskState(
                    state.task_id, state.completion_key, state.game_day_id,
                    TaskStateStatus.BLOCKED, None, state.revision + 1,
                    "DONE_REQUIRES_VERIFIED_MATCHING_COMPLETION_KEY",
                )
            else:
                updated = TaskState(
                    state.task_id, state.completion_key, state.game_day_id,
                    TaskStateStatus.DONE, None, state.revision + 1, result.reason,
                )
        elif result.outcome == TaskOutcome.FAILED_SAFE:
            updated = TaskState(
                state.task_id, state.completion_key, state.game_day_id,
                TaskStateStatus.BLOCKED, None, state.revision + 1, result.reason,
            )
        else:
            updated = TaskState(
                state.task_id, state.completion_key, state.game_day_id,
                TaskStateStatus.PENDING, now_monotonic + backoff_seconds,
                state.revision + 1, result.reason,
            )
        self._states[task_id] = updated
        return updated

    def mark_unresolved(self, task_id: str, reason: str) -> TaskState:
        state = self._states.get(task_id)
        if state is None:
            raise SchedulerError("unknown task")
        updated = TaskState(
            state.task_id, state.completion_key, state.game_day_id,
            TaskStateStatus.UNRESOLVED, None, state.revision + 1, reason,
        )
        self._states[task_id] = updated
        return updated

    def reconcile_unresolved(self, task_id: str, result: TaskResult) -> TaskState:
        state = self._states.get(task_id)
        if state is None:
            raise SchedulerError("unknown task")
        if state.status != TaskStateStatus.UNRESOLVED:
            raise SchedulerError("task is not unresolved")
        if result.outcome == TaskOutcome.DONE and result.verified and result.completion_key == state.completion_key:
            updated = TaskState(state.task_id, state.completion_key, state.game_day_id, TaskStateStatus.DONE, None, state.revision + 1, result.reason)
        else:
            updated = TaskState(state.task_id, state.completion_key, state.game_day_id, TaskStateStatus.BLOCKED, None, state.revision + 1, "unresolved_reconciliation_not_positive")
        self._states[task_id] = updated
        return updated

    def to_json(self) -> str:
        payload = {
            "schema": STATE_SCHEMA,
            "states": [
                {
                    **asdict(state),
                    "status": state.status.value,
                }
                for state in self.snapshot()
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "OnePulseScheduler":
        try:
            payload: Mapping[str, Any] = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SchedulerError("invalid task-state JSON") from exc
        if payload.get("schema") != STATE_SCHEMA or not isinstance(payload.get("states"), list):
            raise SchedulerError("unsupported task-state schema")
        states = []
        for item in payload["states"]:
            if not isinstance(item, Mapping):
                raise SchedulerError("task state entry must be an object")
            try:
                states.append(
                    TaskState(
                        task_id=str(item["task_id"]),
                        completion_key=str(item["completion_key"]),
                        game_day_id=str(item["game_day_id"]),
                        status=TaskStateStatus(str(item.get("status", TaskStateStatus.PENDING.value))),
                        next_due_monotonic=item.get("next_due_monotonic"),
                        revision=int(item.get("revision", 0)),
                        last_reason=str(item.get("last_reason", "")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SchedulerError("invalid task state entry") from exc
        return cls(states)


class SQLiteBackedOnePulseScheduler:
    """Persist scheduler mutations through a TaskStateRepository and reload deterministically."""

    def __init__(self, repository: TaskStateRepository) -> None:
        self.repository = repository
        self.scheduler = OnePulseScheduler(repository.list())

    def refresh(self) -> None:
        self.scheduler = OnePulseScheduler(self.repository.list())

    def snapshot(self) -> tuple[TaskState, ...]:
        return self.scheduler.snapshot()

    def next_pulse(
        self,
        now_monotonic: float,
        game_day_id: str,
        *,
        lease_valid: bool,
        unresolved_action: bool,
    ) -> Optional[PulseCandidate]:
        return self.scheduler.next_pulse(
            now_monotonic,
            game_day_id,
            lease_valid=lease_valid,
            unresolved_action=unresolved_action,
        )

    def record_result(
        self,
        task_id: str,
        result: TaskResult,
        now_monotonic: float,
        *,
        backoff_seconds: float = 60.0,
    ) -> TaskState:
        updated = self.scheduler.record_result(task_id, result, now_monotonic, backoff_seconds=backoff_seconds)
        self.repository.save(updated, now_monotonic)
        return updated

    def mark_unresolved(self, task_id: str, reason: str, updated_at: float) -> TaskState:
        updated = self.scheduler.mark_unresolved(task_id, reason)
        self.repository.save(updated, updated_at)
        return updated

    def reconcile_unresolved(self, task_id: str, result: TaskResult, updated_at: float) -> TaskState:
        updated = self.scheduler.reconcile_unresolved(task_id, result)
        self.repository.save(updated, updated_at)
        return updated
