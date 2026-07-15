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
from .popup import (
    ALLIANCE_FORT_WAVE_ALERT,
    UPDATE_RESTART_ALERT,
    PopupController,
    PopupObservation,
    alliance_fort_dismissal_allowed,
    classify_popup_semantics,
    popup_dismissal_verified,
)

__all__ = [
    "ActionClass",
    "ALLIANCE_FORT_WAVE_ALERT",
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
    "UPDATE_RESTART_ALERT",
    "alliance_fort_dismissal_allowed",
    "classify_popup_semantics",
    "ocr_reuse_denial",
    "popup_dismissal_verified",
    "roi_hash_map",
    "sha256_bytes",
]
