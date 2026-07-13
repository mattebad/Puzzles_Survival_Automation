"""Deterministic, fail-closed supervised action safety core."""

from .executor import ExecutionResult, SafeActionExecutor
from .freshness import ocr_reuse_denial, roi_hash_map, sha256_bytes
from .models import (
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

__all__ = [
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
    "SafeActionExecutor",
    "SafetyStore",
    "TransportResult",
    "ocr_reuse_denial",
    "roi_hash_map",
    "sha256_bytes",
]
