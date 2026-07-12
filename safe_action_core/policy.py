"""Single central authorization boundary for supervised R1 input."""

from __future__ import annotations

import re
from typing import Tuple

from .models import PolicyDecision, PolicyRequest, PolicyResult, snapshot

SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_SIZE = (800, 1280)
DEFAULT_SUPERVISED_TASKS = frozenset({"MVP-QUEST-TO-CLAIM"})
ALLOWED_R1_CONSEQUENCES = frozenset(
    {
        "claim_zero_cost_reward",
        "alliance_help_zero_cost",
        "supply_depot_free_claim",
        "navigate_zero_cost",
    }
)


class CentralPolicy:
    """Fail closed unless every supervised zero-cost condition is explicit."""

    def __init__(self, supervised_tasks=None):
        selected = DEFAULT_SUPERVISED_TASKS if supervised_tasks is None else supervised_tasks
        self.supervised_tasks = frozenset(selected)

    def evaluate(self, request: PolicyRequest) -> PolicyResult:
        decision, code, reason = self._decide(request)
        return PolicyResult(
            decision=decision,
            reason_code=code,
            reason=reason,
            evaluated_at=request.now,
            request_snapshot=snapshot(request),
        )

    def _decide(self, req: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
        obs = req.observation
        lock = PolicyDecision.GLOBAL_INPUT_LOCK
        deny = PolicyDecision.DENY

        if obs.runtime_profile_id != req.expected_runtime_profile_id:
            return lock, "PROFILE_MISMATCH", "runtime profile does not match the locked profile"
        if not obs.valid_png or obs.corrupt or obs.black or (obs.width, obs.height) != EXPECTED_SIZE:
            return lock, "INVALID_FRAME", "frame is corrupt, black, invalid, or profile-sized incorrectly"
        if req.unresolved_action:
            return lock, "UNRESOLVED_ACTION", "an unresolved consequential action blocks input"
        if not req.lease_valid or not req.lease_owner:
            return deny, "LEASE_REQUIRED", "an exclusive valid controller lease is required"
        if req.duplicate_action_key:
            return deny, "DUPLICATE_ACTION_KEY", "the deterministic action key already exists"
        if req.task_mode != "supervised_validation":
            return deny, "TASK_MODE_DENIED", "task is not enabled for supervised validation"
        if req.task_id not in self.supervised_tasks:
            return deny, "TASK_NOT_ENABLED", "task identity is not explicitly enabled for supervised validation"
        if req.now - obs.captured_at < 0 or req.now - obs.captured_at > req.max_frame_age_seconds:
            return deny, "STALE_FRAME", "source frame is stale or timestamped in the future"
        if not SHA256.fullmatch(obs.frame_sha256):
            return deny, "INVALID_FRAME_HASH", "source frame hash is missing or malformed"
        if not obs.recognized or not obs.source_state or obs.source_state == "UNKNOWN":
            return deny, "UNKNOWN_SOURCE", "source state is not positively recognized"
        if obs.overlay_state not in ("none", "none_observed"):
            return deny, "UNKNOWN_OVERLAY", "overlay state is not an exact clear state"
        if not obs.target_identity or not obs.target_roi:
            return deny, "SEMANTIC_TARGET_REQUIRED", "coordinate-only or unknown targets are denied"
        if len(obs.target_roi) != 4 or obs.target_roi[0] >= obs.target_roi[2] or obs.target_roi[1] >= obs.target_roi[3]:
            return deny, "INVALID_TARGET_ROI", "target ROI is invalid"
        if obs.target_roi[0] < 0 or obs.target_roi[1] < 0 or obs.target_roi[2] > obs.width or obs.target_roi[3] > obs.height:
            return deny, "INVALID_TARGET_ROI", "target ROI is outside the source frame"
        if obs.clipped:
            return deny, "CLIPPED_TARGET", "clipped rows cannot authorize input"
        if obs.ambiguous:
            return deny, "AMBIGUOUS_TARGET", "ambiguous rows or targets cannot authorize input"
        if obs.control_class == "GO" and req.semantic_action == "CLAIM_DAILY_QUEST":
            return deny, "GO_NOT_CLAIM", "Go cannot be classified or authorized as Claim"
        if req.semantic_action == "CLAIM_DAILY_QUEST" and obs.control_class != "CLAIM":
            return deny, "CLAIM_TARGET_NOT_RECOGNIZED", "Claim requires an exact Claim control classification"
        if not obs.consequence or obs.consequence == "unknown":
            return deny, "UNKNOWN_CONSEQUENCE", "consequence must be exact and known"
        if not obs.expected_postcondition:
            return deny, "POSTCONDITION_REQUIRED", "an exact expected postcondition is required"
        if obs.cost_type is None or obs.cost_amount is None:
            return deny, "UNKNOWN_COST", "cost type and amount must be known"
        if obs.quantity is None or obs.quantity <= 0:
            return deny, "UNKNOWN_QUANTITY", "quantity must be known and positive"
        if obs.cost_type != "none" or obs.cost_amount != 0:
            code = "PREMIUM_COST_DENIED" if obs.cost_type in ("premium", "real_money") else "RESOURCE_COST_DENIED"
            return deny, code, "premium, resource, item, AP, stamina, march, queue, combat, and strategic costs are denied"
        if obs.consequence not in ALLOWED_R1_CONSEQUENCES:
            return deny, "CONSEQUENCE_DENIED", "the consequence is not allowlisted for supervised zero-cost R1"
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_ZERO_COST_R1", "all supervised zero-cost R1 guards passed"
