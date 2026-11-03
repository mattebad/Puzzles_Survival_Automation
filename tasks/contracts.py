"""Small, typed contracts shared by deterministic task modules.

The contracts deliberately contain no device or filesystem access.  A task becomes complete
only after its caller supplies a positively verified result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

ROI = Tuple[int, int, int, int]


class TaskOutcome(str, Enum):
    PROGRESS = "progress"
    DONE = "done"
    RETRY = "retry"
    BLOCKED = "blocked"
    FAILED_SAFE = "failed_safe"


@dataclass(frozen=True)
class ActionTransactionSpec:
    action_kind: str
    expected_source_screen: str
    subject: str
    quantity: Optional[int]
    resource_or_currency: Optional[str]
    maximum_cost: Optional[float]
    free_only: bool
    allowed_confirmation_dialogs: Tuple[str, ...] = ()
    semantic_preconditions: Tuple[str, ...] = ()
    semantic_postconditions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskResult:
    outcome: TaskOutcome
    reason: str
    verified: bool = False
    state: Optional[str] = None
    completion_key: Optional[str] = None
    details: dict = field(default_factory=dict)

    @classmethod
    def progress(cls, reason: str, state: Optional[str] = None, **details) -> "TaskResult":
        return cls(TaskOutcome.PROGRESS, reason, True, state, None, details)

    @classmethod
    def done(cls, reason: str, completion_key: str, state: Optional[str] = None, **details) -> "TaskResult":
        return cls(TaskOutcome.DONE, reason, True, state, completion_key, details)
