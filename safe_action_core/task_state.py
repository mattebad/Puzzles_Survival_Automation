"""SQLite adapter for the offline Phase F task-state contract."""

from __future__ import annotations

from typing import Optional

from tasks.scheduler import TaskState, TaskStateStatus

from .store import SafetyStore


class SQLiteTaskStateRepository:
    """Persist TaskState snapshots in the existing SafetyStore database."""

    def __init__(self, store: SafetyStore) -> None:
        self.store = store

    def save(self, state: TaskState, updated_at: float) -> TaskState:
        self.store.upsert_task_state(
            {
                "task_id": state.task_id,
                "completion_key": state.completion_key,
                "game_day_id": state.game_day_id,
                "status": state.status.value,
                "next_due_monotonic": state.next_due_monotonic,
                "revision": state.revision,
                "last_reason": state.last_reason,
            },
            updated_at,
        )
        return state

    @staticmethod
    def _from_row(row: dict) -> TaskState:
        return TaskState(
            task_id=row["task_id"],
            completion_key=row["completion_key"],
            game_day_id=row["game_day_id"],
            status=TaskStateStatus(row["status"]),
            next_due_monotonic=row["next_due_monotonic"],
            revision=int(row["revision"]),
            last_reason=row["last_reason"],
        )

    def get(self, task_id: str) -> Optional[TaskState]:
        row = self.store.get_task_state(task_id)
        return self._from_row(row) if row is not None else None

    def list(self) -> tuple[TaskState, ...]:
        return tuple(self._from_row(row) for row in self.store.list_task_states())
