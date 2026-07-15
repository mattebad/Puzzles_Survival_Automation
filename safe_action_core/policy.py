"""Single central authorization boundary for supervised R1 input."""

from __future__ import annotations

import re
from typing import Tuple

from .models import ActionClass, PolicyDecision, PolicyRequest, PolicyResult, snapshot
from .promotional import (
    MAX_PROMOTIONAL_BACKS,
    PROMOTIONAL_BACK_GEOMETRY,
    PROMOTIONAL_BACK_TARGET_ROI,
    PROMOTIONAL_STATE,
    SAFE_PROMOTIONAL_BACK,
)

SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_SIZE = (800, 1280)
DEFAULT_SUPERVISED_TASKS = frozenset({"MVP-QUEST-TO-CLAIM"})
ALLOWED_R1_CONSEQUENCES = frozenset(
    {
        "claim_zero_cost_reward",
        "alliance_help_zero_cost",
        "praise_zero_cost",
        "supply_depot_free_claim",
        "bioenhancer_research_free",
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
            evaluated_at=request.monotonic_now,
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
        age = req.monotonic_now - obs.capture_completed_monotonic
        limit = (
            req.dispatch_max_age_seconds
            if req.policy_phase == "pre_dispatch"
            else req.observation_max_age_seconds
        )
        if age < 0 or age > limit:
            return deny, "STALE_FRAME", "source frame is stale or timestamped in the future"
        if not SHA256.fullmatch(obs.frame_sha256):
            return deny, "INVALID_FRAME_HASH", "source frame hash is missing or malformed"
        if obs.ocr_result_frame_sha256 is not None and not SHA256.fullmatch(obs.ocr_result_frame_sha256):
            return deny, "INVALID_PERCEPTION_BINDING", "OCR result frame binding is malformed"
        if obs.ocr_result_frame_sha256 is not None and obs.ocr_result_capture_completed_monotonic is None:
            return deny, "INVALID_PERCEPTION_BINDING", "OCR result capture binding is missing"
        if not obs.ocr_reused and obs.ocr_result_frame_sha256 is not None and (
            obs.ocr_result_frame_sha256 != obs.frame_sha256
            or obs.ocr_result_capture_completed_monotonic != obs.capture_completed_monotonic
        ):
            return deny, "INVALID_PERCEPTION_BINDING", "fresh OCR must bind to the immediate frame and capture"
        if obs.ocr_reused and (
            obs.ocr_result_capture_completed_monotonic is None
            or obs.ocr_result_capture_completed_monotonic >= obs.capture_completed_monotonic
        ):
            return deny, "INVALID_PERCEPTION_BINDING", "OCR reuse must identify an earlier completed capture"
        if any(not name or not SHA256.fullmatch(digest) for name, digest in obs.critical_roi_hashes):
            return deny, "INVALID_PERCEPTION_BINDING", "critical ROI bindings are missing or malformed"
        if req.action_class == ActionClass.SPEND_OR_STRATEGIC:
            return deny, "SPEND_OR_STRATEGIC_DISABLED", "spend and strategic actions remain disabled"
        if req.semantic_action == SAFE_PROMOTIONAL_BACK:
            return self._decide_promotional_back(req)
        if not obs.recognized or not obs.source_state or obs.source_state == "UNKNOWN":
            return deny, "UNKNOWN_SOURCE", "source state is not positively recognized"
        if obs.overlay_state not in ("none", "none_observed"):
            if not (
                req.semantic_action == "DISMISS_RESET_POPUP"
                and obs.overlay_state == "known_reset_popup"
            ) and not (
                req.semantic_action == "DISMISS_ALLIANCE_FORT_WAVE"
                and obs.overlay_state == "alliance_fort_wave_alert"
            ):
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
        if req.action_class == ActionClass.NAVIGATION_ONLY:
            if obs.os_surface or obs.hard_stop_detected or not obs.package_foreground:
                return lock, "NAVIGATION_HARD_STOP", "foreground, OS, or account/session safety is not proven"
            if obs.forbidden_region_intersects_target:
                return deny, "NAVIGATION_TARGET_DANGEROUS", "the local target intersects a dangerous control"
            if req.semantic_action == "DISMISS_ALLIANCE_FORT_WAVE":
                if (
                    obs.source_state != "ALLIANCE_FORT_WAVE_ALERT"
                    or obs.target_identity not in {
                        "alliance-fort-wave-dismiss-x",
                        "alliance-fort-wave-dismiss-confirm",
                    }
                    or obs.control_class not in {"POPUP_DISMISS_X", "POPUP_DISMISS_CONFIRM"}
                    or obs.expected_postcondition != "ALLIANCE_FORT_DISMISSED"
                ):
                    return deny, "ALLIANCE_FORT_DISMISSAL_NOT_EXACT", "only exact Alliance Fort X or Confirm dismissal is allowed"
            if obs.consequence != "navigate_zero_cost" or not obs.expected_postcondition:
                return deny, "NAVIGATION_CONTRACT_INVALID", "navigation requires a zero-cost bounded successor"
            if obs.cost_type != "none" or obs.cost_amount != 0 or obs.quantity != 1:
                return deny, "NAVIGATION_COST_DENIED", "navigation must be one zero-cost input"
            if req.semantic_action == "DISMISS_RESET_POPUP":
                if obs.source_state != "RESET_POPUP" or obs.target_identity != "reset-popup-close":
                    return deny, "RESET_POPUP_CLOSE_REQUIRED", "only the recognized reset popup Close control is allowed"
                if obs.expected_postcondition != "HOME_BASE":
                    return deny, "RESET_POPUP_SUCCESSOR_REQUIRED", "reset popup dismissal must return to Home/Base"
                x0, y0, x1, y1 = obs.target_roi
                if x0 < 200 or y0 < 700 or x1 > 600 or y1 > 920:
                    return deny, "RESET_POPUP_CLOSE_ROI_INVALID", "reset popup Close target is outside its bounded ROI"
            return PolicyDecision.AUTHORIZE, "AUTHORIZED_NAVIGATION_ONLY", "local source, target, overlay, and successor guards passed"
        if req.semantic_action == "RESEARCH_BIOENHANCER_FREE":
            if not req.game_day_id:
                return deny, "GAME_DAY_REQUIRED", "Bioenhancer research requires a current game-day identity"
            if (
                obs.source_state != "BIOENHANCER"
                or obs.target_identity != "bioenhancer-free-research"
                or obs.control_class != "RESEARCH_FREE"
                or obs.expected_postcondition != "BIOENHANCER_RESEARCH_SUCCESS"
            ):
                return deny, "BIOENHANCER_TARGET_NOT_EXACT", "only the exact current-frame Free Research 1x target is allowed"
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

    @staticmethod
    def _decide_promotional_back(req: PolicyRequest) -> Tuple[PolicyDecision, str, str]:
        """Authorize only an isolated standard game arrow on an unknown promotion."""
        obs = req.observation
        deny = PolicyDecision.DENY
        lock = PolicyDecision.GLOBAL_INPUT_LOCK
        if req.promotional_back_count >= MAX_PROMOTIONAL_BACKS:
            return deny, "PROMOTIONAL_BACK_LIMIT", "the bounded promotional escape limit was reached"
        if obs.os_surface or obs.hard_stop_detected or not obs.package_foreground:
            return lock, "PROMOTIONAL_HARD_STOP", "OS, account/session, or foreground safety is not proven"
        if not obs.recognized or obs.source_state != PROMOTIONAL_STATE or obs.source_family != "promotional":
            return deny, "PROMOTIONAL_SOURCE_NOT_RECOGNIZED", "the source is not an independently recognized promotional surface"
        if obs.overlay_state != "promotional_unknown_nonintersecting":
            return deny, "PROMOTIONAL_OVERLAY_NOT_SAFE", "an unknown overlay is not proven separate from the arrow"
        if obs.target_identity != "standard-game-back-arrow" or obs.control_class != SAFE_PROMOTIONAL_BACK:
            return deny, "PROMOTIONAL_ARROW_TARGET_REQUIRED", "only the recognized standard game Back arrow is allowed"
        if obs.target_roi != PROMOTIONAL_BACK_TARGET_ROI:
            return deny, "PROMOTIONAL_ARROW_ROI_INVALID", "the arrow target must use the locked isolated ROI"
        if obs.clipped:
            return deny, "CLIPPED_TARGET", "the promotional Back arrow is clipped"
        if obs.ambiguous:
            return deny, "AMBIGUOUS_TARGET", "the promotional Back arrow is ambiguous"
        if obs.arrow_geometry != PROMOTIONAL_BACK_GEOMETRY:
            return deny, "PROMOTIONAL_ARROW_GEOMETRY_INVALID", "the standard game Back arrow geometry did not pass"
        if not obs.forbidden_regions:
            return deny, "PROMOTIONAL_FORBIDDEN_REGIONS_REQUIRED", "forbidden interactive regions must be explicitly bound"
        x0, y0, x1, y1 = obs.target_roi
        for _name, region in obs.forbidden_regions:
            if len(region) != 4 or region[0] >= region[2] or region[1] >= region[3]:
                return deny, "PROMOTIONAL_FORBIDDEN_REGION_INVALID", "forbidden region metadata is invalid"
            fx0, fy0, fx1, fy1 = region
            if not (x1 <= fx0 or fx1 <= x0 or y1 <= fy0 or fy1 <= y0):
                return deny, "PROMOTIONAL_TARGET_NOT_ISOLATED", "the arrow ROI intersects a forbidden control region"
        if not obs.target_isolated or obs.forbidden_region_intersects_target:
            return deny, "PROMOTIONAL_TARGET_NOT_ISOLATED", "the arrow ROI is not separated from forbidden controls"
        if not obs.consequence or obs.consequence != "navigate_zero_cost":
            return deny, "PROMOTIONAL_CONSEQUENCE_DENIED", "promotional escape is navigation-only"
        if obs.cost_type != "none" or obs.cost_amount != 0:
            return deny, "PROMOTIONAL_COST_DENIED", "promotional escape must have exactly zero cost"
        if obs.quantity != 1:
            return deny, "PROMOTIONAL_QUANTITY_DENIED", "promotional escape quantity must be exactly one"
        if not obs.expected_postcondition:
            return deny, "PROMOTIONAL_SUCCESSOR_REQUIRED", "a bounded expected successor is required"
        successor = obs.expected_postcondition.upper().replace("-", "_")
        allowed_successors = {
            "CASH_MALL", "HOME_BASE", "QUEST", "DAILY_QUEST",
            "UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK", "RECOGNIZED_NAVIGATION_STATE",
        }
        if successor not in allowed_successors:
            return deny, "PROMOTIONAL_SUCCESSOR_DENIED", "successor is outside the bounded navigation-only set"
        return PolicyDecision.AUTHORIZE, "AUTHORIZED_SAFE_PROMOTIONAL_BACK", "isolated verified promotional Back guards passed"
