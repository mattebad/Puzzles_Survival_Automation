"""Deterministic, fail-closed supervised action safety core."""

from .executor import ActionTransaction, ExecutionResult, SafeActionExecutor
from .freshness import ocr_reuse_denial, roi_hash_map, sha256_bytes
from .models import (
    ActionClass,
    ActionIntent,
    ActionStatus,
    Observation,
    PolicyDecision,
    PolicyRequest,
    PolicyResult,
    TransportResult,
)
from .policy import CentralPolicy
from .promotional import (
    MAX_PROMOTIONAL_BACKS,
    PromotionalBackSequence,
    PromotionalSequenceError,
)
from .store import CURRENT_SCHEMA_VERSION, SafetyStore
from .task_state import SQLiteTaskStateRepository
from .popup import PopupController, PopupObservation

__all__ = [
    "ActionClass",
    "ActionTransaction",
    "ActionIntent",
    "ActionStatus",
    "CentralPolicy",
    "MAX_PROMOTIONAL_BACKS",
    "CURRENT_SCHEMA_VERSION",
    "ExecutionResult",
    "Observation",
    "PolicyDecision",
    "PolicyRequest",
    "PolicyResult",
    "PromotionalBackSequence",
    "PromotionalSequenceError",
    "PopupController",
    "PopupObservation",
    "SafeActionExecutor",
    "SafetyStore",
    "SQLiteTaskStateRepository",
    "TransportResult",
    "ocr_reuse_denial",
    "roi_hash_map",
    "sha256_bytes",
]
