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
class AnchorSpec:
    """A fixed-profile local anchor with its own evidence-backed recognition budget."""

    name: str
    roi: ROI
    threshold: float
    template: Optional[str] = None
    ocr_rule: Optional[str] = None
    required_confirmation_frames: int = 1
    polling_interval_seconds: float = 0.1
    timeout_seconds: float = 3.0
    attempt_cap: Optional[int] = None
    tap_offset: Tuple[int, int] = (0, 0)
    asset_provenance: str = ""
    reference_manifest_ids: Tuple[str, ...] = ()
    production_validated: bool = True
    evidence_dependency: Optional[str] = None

    def __post_init__(self) -> None:
        x0, y0, x1, y1 = self.roi
        if not self.name or not (0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 1280):
            raise ValueError("AnchorSpec ROI must be an absolute Bliss 800x1280 ROI")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("anchor threshold must be between 0 and 1")
        if self.template is None and self.ocr_rule is None:
            raise ValueError("anchor requires a template or constrained OCR rule")
        if self.required_confirmation_frames < 1:
            raise ValueError("at least one confirmation frame is required")
        if self.polling_interval_seconds <= 0 or self.timeout_seconds <= 0:
            raise ValueError("anchor polling and timeout must be positive")
        if self.attempt_cap is not None and self.attempt_cap < 1:
            raise ValueError("anchor attempt cap must be positive")
        if any(not item.startswith("GNB-") for item in self.reference_manifest_ids):
            raise ValueError("reference manifest IDs must use stable GNB- identifiers")
        if not self.production_validated and not self.evidence_dependency:
            raise ValueError("provisional anchor requires an explicit evidence dependency")


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
