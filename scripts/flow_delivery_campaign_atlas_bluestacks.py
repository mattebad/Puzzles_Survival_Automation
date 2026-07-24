#!/usr/bin/env python3
"""Checked-in BlueStacks operator for Campaign atlas native survey delivery.

Crash-safe lifecycle: prepared -> SafeActionExecutor transport -> input_sent
(+budget) -> terminal|unresolved. Direct LocalBlueStacksRuntime.swipe/tap is
never the action authority. Survey controls are bound from each current native
frame and every post-input successor is independently reconciled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from safe_action_core import (
    ActionClass,
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
)
from scripts.bluestacks_flow_collector import ADBRunner
from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
from scripts.campaign_atlas_bluestacks import report_from_dict
from scripts.personal_might_praise_live import (
    MAX_VIP_POPUP_INPUTS,
    RESET_POPUP_CLOSE_REGION,
    recognize_reset_popup,
    vip_popup_handled,
)
from scripts.home_atlas_bluestacks import (
    BlueStacksHostZoomTransport,
    BlueStacksLocalizeFirstHomeDriver,
    CAMPAIGN_HOME_ATLAS_BUILDING_ID,
    HomeDriverDisposition,
    gesture_geometry_roi,
    load_home_atlas,
    require_campaign_home_atlas_building,
    run_verified_campaign_home_atlas_entry,
)
from scripts.navigation_development_boundary import (
    NavigationBoundaryError,
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    make_source_safety_facts,
)
from tasks.home_context import HomeReadyObservation
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity
from tasks.campaign_atlas import (
    ACTIVATED_AUXILIARY_INPUTS,
    ACTIVATED_EDGE_STEPS_PER_DIRECTION,
    ACTIVATED_EDGE_STEPS_TOTAL,
    ACTIVATED_OVERLAP_STEPS,
    ACTIVATED_TRANSPORT_INPUT_CEILING,
    CAMPAIGN_PACKAGE,
    CAMPAIGN_PLATFORM,
    CAMPAIGN_PROFILE_ID,
    CollectorDisposition,
    ContractKind,
    CoverageGapReport,
    CrossDifficultyGeometryReport,
    EdgeClampReport,
    FrameClassification,
    FrameDisposition,
    InputBudgetAccounting,
    InputBudgetCategory,
    InputLifecycle,
    LandmarkBindingReport,
    LandmarkKind,
    LoopClosureReport,
    MASK_CONTRACT_ID,
    NativeFrameProvenance,
    NavigationEvidenceSequence,
    NavigationJournalEntry,
    OverlapAssociationReport,
    SafeTerminalReport,
    SurveyPhase,
    SurveySessionManifest,
    SurveySessionReport,
    live_survey_preflight_blockers,
    live_survey_preflight_is_admissible,
    validate_survey_session_report,
)
from tasks.campaign_atlas_vision import (
    OrbTranslationBackend,
    chapter_roi_from_strong_spatial_evidence,
    frame_digest,
    hud_safe_pan_gesture,
    loop_closure_accepted,
    measure_campaign_frame_pair,
    measured_survey_target,
    measured_content_annotation_roi,
    overlap_association_accepted,
    prison_trial_roi_from_strong_spatial_evidence,
    registration_progress_outcome,
    registration_residual_report,
    require_tier_map_selection_state,
    survey_target_is_consequential,
)
from tasks.campaign_auto_battle import CampaignScreen, parse_supported_campaign_story_destination
from tasks.campaign_auto_battle_vision import MAP_SEARCH_ROI, recognize_campaign_frame
from tasks.ultimate_challenge_daily import (
    entry_observation_is_bound,
    recognize_ultimate_challenge_entry_from_texts,
    ultimate_challenge_entry_roi_from_ocr_hits,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_ID = "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
SURVEY_RUNNER_ID = "campaign_atlas_native_survey_runner"
SURVEY_EVIDENCE_VALIDATOR_ID = "campaign_atlas_native_survey_evidence"
SURVEY_RECOVERY_HANDLER_ID = "campaign_atlas_native_survey_recovery"
DEFAULT_HOME_ATLAS = (
    REPO_ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
)
_CLASSIFIER_STAGE = parse_supported_campaign_story_destination("1-20-9")
_DIRECTIONS = ("top", "right", "bottom", "left")
_PHASE_FOR_DIRECTION = {
    "top": SurveyPhase.EDGE_TOP,
    "right": SurveyPhase.EDGE_RIGHT,
    "bottom": SurveyPhase.EDGE_BOTTOM,
    "left": SurveyPhase.EDGE_LEFT,
}
ACCOUNTING_PATH = "survey-accounting.json"
LIFECYCLE_PATH = "survey-lifecycle.jsonl"
FRAME_CLASSIFICATION_PATH = "retained-frame-classification.json"
CONTINUATION_PATH = "survey-continuation.json"
_SURVEY_TRANSPORT_SEAL = object()
SURVEY_PAN_SEMANTIC_ACTION = "CAMPAIGN_ATLAS_MAP_PAN"
SURVEY_TAP_SEMANTIC_ACTION = "CAMPAIGN_ATLAS_MAP_TAP"
SURVEY_PAN_POSTCONDITION = "CAMPAIGN_TIER_MAP_VIEWPORT_PROGRESS"
SURVEY_TAP_POSTCONDITION = "CAMPAIGN_NAVIGATION_SUCCESSOR"
VIP_RESET_DISMISS_SEMANTIC_ACTION = "DISMISS_RESET_POPUP"
VIP_RESET_DISMISS_POSTCONDITION = "CAMPAIGN_TIER_MAP"
VIP_RESET_CLOSE_ACTION_KEY = "vip-reset-close"
VIP_RESET_CLOSE_TARGET_IDENTITY = "reset-popup-close"
# Narrow, evidence-backed continuation for the exact accepted prior AUX terminal list.
# Session A: one bounded_home_zoom_out. Session B: three imported Home-atlas entry AUX.
# Zero-input VIP popup-block session survey-20260724T002912186392Z is retained and never counted.
KNOWN_CONTINUATION_PRIOR_EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "session_id": "survey-20260723T232154448911Z",
        "count": 1,
        "terminal": "bounded_home_zoom_out",
        "require_full_lifecycle": True,
    },
    {
        "session_id": "survey-20260724T000253173324Z",
        "count": 3,
        "terminal": "imported_home_atlas_safe_action",
        "require_full_lifecycle": False,
    },
)
KNOWN_CONTINUATION_PRIOR_SESSION_IDS = tuple(
    str(item["session_id"]) for item in KNOWN_CONTINUATION_PRIOR_EVIDENCE
)
KNOWN_CONTINUATION_PRIOR_SESSION_ID = KNOWN_CONTINUATION_PRIOR_SESSION_IDS[0]
KNOWN_CONTINUATION_PRIOR_TERMINAL = str(KNOWN_CONTINUATION_PRIOR_EVIDENCE[0]["terminal"])
KNOWN_CONTINUATION_PRIOR_CATEGORY = InputBudgetCategory.AUXILIARY
KNOWN_CONTINUATION_PRIOR_COUNT = sum(int(item["count"]) for item in KNOWN_CONTINUATION_PRIOR_EVIDENCE)
# Edge-clamp progress may join continuation only after an offline reconciliation receipt.
KNOWN_CONTINUATION_MIXED_CATEGORY = "mixed_auxiliary_and_edge_clamp"
KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE: dict[str, Any] = {
    "session_id": "survey-20260724T004227747200Z",
    "action_key": "edge-top-00",
    "count": 1,
    "category": InputBudgetCategory.EDGE_CLAMP.value,
    "terminal": "progress",
    "receipt_name": "edge-top-00-offline-reconciliation.json",
}
KNOWN_CONTINUATION_RECONCILED_EDGE_COUNT = int(
    KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE["count"]
)
KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE = (
    KNOWN_CONTINUATION_PRIOR_COUNT + KNOWN_CONTINUATION_RECONCILED_EDGE_COUNT
)
KNOWN_CONTINUATION_CUMULATIVE_SESSION_IDS = (
    *KNOWN_CONTINUATION_PRIOR_SESSION_IDS,
    str(KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE["session_id"]),
)
# Retained zero-input popup-block session: never seeds budget and never authorizes resume.
KNOWN_CONTINUATION_EXCLUDED_ZERO_INPUT_POPUP_SESSION_ID = "survey-20260724T002912186392Z"
# Accepted traversal session stopped after successful difficulty-tier-1; resume at tier2 only.
KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY = (
    "traversal_complete_resume_difficulty_tier2"
)
KNOWN_CONTINUATION_TRAVERSAL_SESSION: dict[str, Any] = {
    "session_id": "survey-20260724T012057293610Z",
    "auxiliary_used": 5,
    "edge_clamp_used": 24,
    "overlap_used": 62,
    "transport_inputs_used": 91,
    "session_navigation_inputs_sent": 86,
    "prior_inputs_seeded_inside_session": 5,
    "completed_action_key": "difficulty-tier-1",
    "resume_action_key": "difficulty-tier-2",
    "retained_tier1_post_frame": "runtime/frames/0259-difficulty-tier-1-post.png",
    "retained_tier1_immediate_before_frame": (
        "runtime/frames/0261-difficulty-tier-2-immediate-before.png"
    ),
}
KNOWN_CONTINUATION_CUMULATIVE_WITH_TRAVERSAL = int(
    KNOWN_CONTINUATION_TRAVERSAL_SESSION["transport_inputs_used"]
)
KNOWN_CONTINUATION_TRAVERSAL_SESSION_IDS = (
    *KNOWN_CONTINUATION_CUMULATIVE_SESSION_IDS,
    str(KNOWN_CONTINUATION_TRAVERSAL_SESSION["session_id"]),
)
# Accepted difficulty-tier-2 AUX terminal; resume at campaign-exit-home only.
KNOWN_CONTINUATION_EXIT_RESUME_CATEGORY = "traversal_complete_resume_campaign_exit"
KNOWN_CONTINUATION_TIER2_EXIT_SESSION: dict[str, Any] = {
    "session_id": "survey-20260724T021222146973Z",
    "auxiliary_used": 6,
    "edge_clamp_used": 24,
    "overlap_used": 62,
    "transport_inputs_used": 92,
    "session_navigation_inputs_sent": 1,
    "prior_inputs_seeded_inside_session": 91,
    "completed_action_key": "difficulty-tier-2",
    "resume_action_key": "campaign-exit-home",
    "retained_tier2_post_frame": "runtime/frames/0004-difficulty-tier-2-post.png",
    "retained_exit_immediate_before_frame": (
        "runtime/frames/0006-campaign-exit-home-immediate-before.png"
    ),
    "retained_traversal_session_id": str(
        KNOWN_CONTINUATION_TRAVERSAL_SESSION["session_id"]
    ),
}
KNOWN_CONTINUATION_CUMULATIVE_WITH_TIER2_EXIT = int(
    KNOWN_CONTINUATION_TIER2_EXIT_SESSION["transport_inputs_used"]
)
KNOWN_CONTINUATION_EXIT_SESSION_IDS = (
    *KNOWN_CONTINUATION_TRAVERSAL_SESSION_IDS,
    str(KNOWN_CONTINUATION_TIER2_EXIT_SESSION["session_id"]),
)
RECONCILIATION_RECEIPT_KIND = "campaign_atlas_survey_offline_reconciliation"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def production_survey_call_graph() -> dict[str, str]:
    return {
        "home_zoom_recovery": (
            "scripts.flow_delivery_campaign_atlas_bluestacks."
            "recover_home_zoom_before_campaign_entry"
        ),
        "home_zoom_driver": "scripts.home_atlas_bluestacks.BlueStacksLocalizeFirstHomeDriver",
        "home_zoom_transport": "scripts.home_atlas_bluestacks.BlueStacksHostZoomTransport",
        "home_zoom_firewall": (
            "scripts.navigation_development_boundary.NavigationGuardedRuntime.dispatch_zoom_out"
        ),
        "vip_reset_dismiss": (
            "scripts.flow_delivery_campaign_atlas_bluestacks."
            "dismiss_campaign_vip_reset_popup"
        ),
        "vip_reset_recognizer": "scripts.personal_might_praise_live.recognize_reset_popup",
        "home_to_campaign_entry": "scripts.home_atlas_bluestacks.run_verified_campaign_home_atlas_entry",
        "safe_action_executor": "safe_action_core.SafeActionExecutor",
        "campaign_recognizer": "tasks.campaign_auto_battle_vision.recognize_campaign_frame",
        "hud_safe_pan": "tasks.campaign_atlas_vision.hud_safe_pan_gesture",
        "registration_measurement": "tasks.campaign_atlas_vision.measure_campaign_frame_pair",
        "ultimate_landmark_bind": "tasks.ultimate_challenge_daily.recognize_ultimate_challenge_entry_from_texts",
        "operator_interface": "scripts.pnsctl.bluestacks_run_flow",
    }


def campaign_survey_home_zoom_route_declaration() -> NavigationRouteDeclaration:
    """Navigation-only declaration for bounded Home zoom-out before Campaign entry."""

    return NavigationRouteDeclaration(
        allowed_source_states=frozenset({"HOME_BASE"}),
        allowed_target_identities=frozenset(
            {
                CAMPAIGN_HOME_ATLAS_BUILDING_ID,
                "home-zoom-out",
            }
        ),
        allowed_gesture_classes=frozenset({"zoom_out"}),
    )


def _supervised_survey_home_ready(lease_owner: str, session_id: str) -> HomeReadyObservation:
    identity = VerifiedRuntimeIdentity(
        "bluestacks-campaign-atlas-survey",
        "supervised-campaign-atlas-survey",
        "supervised-campaign-atlas-server",
        None,
        RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        (f"lease:{lease_owner}", f"session:{session_id}"),
    )
    return HomeReadyObservation(True, True, identity, False, False)


def recover_home_zoom_before_campaign_entry(
    op: "_SurveyOperator",
    *,
    source_rel: str,
    atlas_path: Path | None = None,
    maximum_zoom_inputs: int = 4,
    settle_seconds: float = 1.0,
    home_driver: BlueStacksLocalizeFirstHomeDriver | None = None,
    zoom_transport: Any | None = None,
    guarded_runtime: NavigationGuardedRuntime | None = None,
) -> dict[str, Any]:
    """Reuse standard Home RECOVER_ZOOM before verified Campaign Home-atlas entry.

    Plans via ``BlueStacksLocalizeFirstHomeDriver``; dispatches only through
    ``NavigationGuardedRuntime.dispatch_zoom_out`` + ``BlueStacksHostZoomTransport``.
    Each successful zoom is AUXILIARY-budgeted with full evidence. Stops fail-closed on
    unknown/ambiguous zoom, repeated frames, or max inputs. Does not open Campaign.
    """

    if maximum_zoom_inputs < 1 or maximum_zoom_inputs > 4:
        raise RuntimeError("home zoom recovery allows 1..4 inputs")
    path = atlas_path or DEFAULT_HOME_ATLAS
    driver = home_driver
    if driver is None:
        building_id = require_campaign_home_atlas_building(path)
        atlas = load_home_atlas(path)
        ready = _supervised_survey_home_ready(op.lease_owner, op.session_id)
        driver = BlueStacksLocalizeFirstHomeDriver(
            atlas,
            path,
            ready,
            building_id,
            maximum_zoom_inputs=maximum_zoom_inputs,
        )
    else:
        building_id = CAMPAIGN_HOME_ATLAS_BUILDING_ID
    transport = zoom_transport
    if transport is None:
        transport = BlueStacksHostZoomTransport()
    guarded = guarded_runtime
    if guarded is None:
        guarded = NavigationGuardedRuntime(
            op.runtime,
            campaign_survey_home_zoom_route_declaration(),
        )

    records: list[dict[str, Any]] = []
    zoom_inputs = 0
    for ordinal in range(1, maximum_zoom_inputs + 1):
        before, _before_prov = op.capture(f"home-zoom-{ordinal:02d}-immediate-before")
        if op.recognize(before.frame).observation.screen != CampaignScreen.HOME_BASE:
            raise RuntimeError(
                "home zoom recovery requires positively recognized HOME_BASE "
                f"(got {op.recognize(before.frame).observation.screen.value})"
            )
        step = driver.observe(before.frame)
        records.append(
            {
                "ordinal": ordinal,
                "disposition": step.disposition.value,
                "reason": step.reason,
                "frame_sha256": step.source_frame_sha256,
                "recovery_input_ordinal": step.recovery_input_ordinal,
            }
        )
        if step.disposition in {
            HomeDriverDisposition.COMPLETE,
            HomeDriverDisposition.BIND,
            HomeDriverDisposition.PAN,
        }:
            return {
                "status": "localized",
                "reason": step.reason,
                "zoom_inputs": zoom_inputs,
                "records": records,
                "building_id": building_id,
            }
        if step.disposition is HomeDriverDisposition.BLOCKED:
            raise RuntimeError(f"home zoom recovery blocked: {step.reason}")
        if step.disposition is not HomeDriverDisposition.RECOVER_ZOOM:
            raise RuntimeError(
                f"home zoom recovery unsupported disposition: {step.disposition.value}"
            )

        action_key = f"home-zoom-{ordinal:02d}"
        transport_path = op.session / f"{action_key}-transport.json"
        transport_path.write_text(
            json.dumps(
                {
                    "action_key": action_key,
                    "gesture": "zoom_out",
                    "authority": "NavigationGuardedRuntime.dispatch_zoom_out",
                    "transport": "BlueStacksHostZoomTransport.zoom_out_once",
                    "driver_reason": step.reason,
                    "recovery_input_ordinal": step.recovery_input_ordinal,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        transport_rel = _rel(op.session, transport_path)
        before_rel = _rel(op.session, before.path)
        journal_ordinal = op.prepare_input(
            phase=SurveyPhase.SAFE_TERMINAL,
            category=InputBudgetCategory.AUXILIARY,
            before_rel=before_rel,
            transport_rel=transport_rel,
            source_rel=source_rel,
            swipe=None,
            prior_progress_proven=False,
            planned_terminal="bounded_home_zoom_out",
        )
        transport_gate: dict[str, bool] = {"attempted": False, "input_sent": False}
        try:
            facts = make_source_safety_facts(
                recognized=True,
                source_state="HOME_BASE",
                frame_sha256=before.sha256,
                captured_monotonic=before.captured_monotonic,
            )
            transport_gate["attempted"] = True
            guarded.dispatch_zoom_out(
                before,
                facts,
                transport=transport.zoom_out_once,
            )
            driver.record_zoom_input_dispatched(step.source_frame_sha256)
            op.mark_input_sent(journal_ordinal, category=InputBudgetCategory.AUXILIARY)
            transport_gate["input_sent"] = True
            zoom_inputs += 1
        except (NavigationBoundaryError, Exception) as exc:
            op._close_dispatch_exception(
                ordinal=journal_ordinal,
                source_rel=source_rel,
                before_rel=before_rel,
                transport_rel=transport_rel,
                exc=exc,
                transport_gate=transport_gate,
            )
            raise RuntimeError(f"home zoom recovery transport failed: {exc}") from exc

        post, _post_prov = op.capture(f"{action_key}-immediate-post")
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        settled, _settled_prov = op.capture(f"{action_key}-settled")
        semantic_path = op.session / f"{action_key}-result.json"
        post_screen = op.recognize(settled.frame).observation.screen
        semantic_path.write_text(
            json.dumps(
                {
                    "gesture": "bounded_zoom_out",
                    "screen": post_screen.value,
                    "before_sha256": before.sha256,
                    "post_sha256": post.sha256,
                    "settled_sha256": settled.sha256,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        evidence = NavigationEvidenceSequence(
            source_path=source_rel,
            immediate_before_path=before_rel,
            transport_record_path=transport_rel,
            immediate_post_path=_rel(op.session, post.path),
            semantic_result_path=_rel(op.session, semantic_path),
        )
        if post_screen != CampaignScreen.HOME_BASE:
            op.mark_terminal(
                journal_ordinal,
                evidence=evidence,
                terminal=f"home_zoom_left_home_base:{post_screen.value}",
                unresolved=True,
            )
            raise RuntimeError(
                f"home zoom recovery left HOME_BASE ({post_screen.value})"
            )
        op.mark_terminal(
            journal_ordinal,
            evidence=evidence,
            terminal="bounded_home_zoom_out",
            unresolved=False,
        )
        records[-1]["transport"] = "dispatched"
        records[-1]["settled_sha256"] = settled.sha256

    # Final observe after max zoom inputs without localization.
    final, _ = op.capture("home-zoom-final-immediate-before")
    if op.recognize(final.frame).observation.screen != CampaignScreen.HOME_BASE:
        raise RuntimeError("home zoom recovery final frame is not HOME_BASE")
    final_step = driver.observe(final.frame)
    records.append(
        {
            "ordinal": maximum_zoom_inputs + 1,
            "disposition": final_step.disposition.value,
            "reason": final_step.reason,
            "frame_sha256": final_step.source_frame_sha256,
        }
    )
    if final_step.disposition in {
        HomeDriverDisposition.COMPLETE,
        HomeDriverDisposition.BIND,
        HomeDriverDisposition.PAN,
    }:
        return {
            "status": "localized",
            "reason": final_step.reason,
            "zoom_inputs": zoom_inputs,
            "records": records,
            "building_id": building_id,
        }
    raise RuntimeError(
        f"home zoom recovery exhausted without localization: {final_step.reason}"
    )


def _vip_close_critical_roi_hashes(frame: np.ndarray) -> tuple[tuple[str, str], ...]:
    x0, y0, x1, y1 = RESET_POPUP_CLOSE_REGION
    crop = frame[y0:y1, x0:x1]
    digest = hashlib.sha256(np.ascontiguousarray(crop).tobytes()).hexdigest()
    return (("popup_close", digest),)


def _build_vip_reset_observation(
    *,
    frame: np.ndarray,
    frame_sha256: str,
    capture_completed_monotonic: float,
    target_roi: tuple[int, int, int, int],
    overlay_state: str = "known_reset_popup",
    recognized: bool = True,
    source_state: str = "RESET_POPUP",
    target_identity: str | None = VIP_RESET_CLOSE_TARGET_IDENTITY,
) -> Observation:
    return Observation(
        frame_sha256=frame_sha256,
        capture_completed_monotonic=float(capture_completed_monotonic),
        runtime_profile_id=CAMPAIGN_PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state=source_state,
        overlay_state=overlay_state,
        target_identity=target_identity,
        target_roi=target_roi if target_identity else None,
        recognized=recognized,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition=VIP_RESET_DISMISS_POSTCONDITION,
        evidence_refs=(f"campaign-atlas:{VIP_RESET_DISMISS_SEMANTIC_ACTION}",),
        critical_roi_hashes=_vip_close_critical_roi_hashes(frame),
        package_foreground=True,
        os_surface=False,
        hard_stop_detected=False,
    )


def dismiss_campaign_vip_reset_popup(
    op: "_SurveyOperator",
    *,
    source_rel: str,
) -> dict[str, Any]:
    """One AUXILIARY VIP Close via SafeActionExecutor before unsupported-start failure.

    Binds issue/consume/tap to one fresh immediate-before identity. Postcondition:
    popup absent and Campaign TIER_MAP. No retry. Unknown/still-popup/wrong
    successor becomes terminal unresolved when transport occurred.
    """

    if getattr(op, "vip_popup_input_count", 0) >= MAX_VIP_POPUP_INPUTS:
        return {
            "status": "blocked",
            "reason": "vip_popup_input_limit_reached",
            "transport_dispatched": False,
        }

    action_key = VIP_RESET_CLOSE_ACTION_KEY
    fresh, _fresh_prov = op.capture(f"{action_key}-immediate-before")
    detail = recognize_reset_popup(fresh.frame)
    fresh_rel = _rel(op.session, fresh.path)
    if not detail.get("recognized") or not detail.get("target") or not detail.get("target_center"):
        return {
            "status": "blocked",
            "reason": "vip_popup_not_recognized",
            "transport_dispatched": False,
            "detail": {
                "recognized": bool(detail.get("recognized")),
                "title_identity": bool(detail.get("title_identity")),
                "body_identity": bool(detail.get("body_identity")),
                "literal_close": bool(detail.get("literal_close")),
                "geometry_valid": bool(detail.get("geometry_valid")),
            },
            "before_rel": fresh_rel,
        }

    target_roi = tuple(int(v) for v in detail["target"])
    proposed_tap = tuple(int(v) for v in detail["target_center"])
    transport = op.session / f"{action_key}-transport.json"
    transport.write_text(
        json.dumps(
            {
                "action_key": action_key,
                "semantic_action": VIP_RESET_DISMISS_SEMANTIC_ACTION,
                "target_identity": VIP_RESET_CLOSE_TARGET_IDENTITY,
                "roi": list(target_roi),
                "tap": list(proposed_tap),
                "authority": "SafeActionExecutor",
                "popup_identity": detail.get("popup_identity"),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    transport_rel = _rel(op.session, transport)
    ordinal = op.prepare_input(
        phase=SurveyPhase.SAFE_TERMINAL,
        category=InputBudgetCategory.AUXILIARY,
        before_rel=fresh_rel,
        transport_rel=transport_rel,
        source_rel=source_rel,
        swipe=None,
        prior_progress_proven=False,
        planned_terminal=VIP_RESET_CLOSE_TARGET_IDENTITY,
    )
    observation = _build_vip_reset_observation(
        frame=fresh.frame,
        frame_sha256=fresh.sha256,
        capture_completed_monotonic=fresh.captured_monotonic,
        target_roi=target_roi,
    )
    post_holder: dict[str, Any] = {}
    transport_gate: dict[str, bool] = {"attempted": False, "input_sent": False}

    def recapture_fn() -> Observation:
        rebuilt = _build_vip_reset_observation(
            frame=fresh.frame,
            frame_sha256=fresh.sha256,
            capture_completed_monotonic=fresh.captured_monotonic,
            target_roi=target_roi,
        )
        if rebuilt is observation:
            raise RuntimeError("RECAPTURE_MUST_REBUILD_DISTINCT_OBSERVATION")
        return replace(
            rebuilt,
            evidence_refs=observation.evidence_refs + (fresh_rel,),
        )

    def transport_fn(_intent) -> TransportResult:
        if op.vip_popup_input_count >= MAX_VIP_POPUP_INPUTS:
            raise RuntimeError("VIP popup input limit reached during dispatch")
        transport_gate["attempted"] = True
        reject_direct_survey_transport(authorized_token=_SURVEY_TRANSPORT_SEAL)
        op.vip_popup_input_count += 1
        op.runtime.tap(
            fresh,
            target_identity=VIP_RESET_CLOSE_TARGET_IDENTITY,
            target_roi=target_roi,
            action_key=action_key,
            consequential=False,
        )
        op.mark_input_sent(ordinal, category=InputBudgetCategory.AUXILIARY)
        transport_gate["input_sent"] = True
        return TransportResult(True, "CAMPAIGN_VIP_RESET_CLOSE_DISPATCHED")

    def post_observe():
        time.sleep(0.8)
        post, post_prov = op.capture(f"{action_key}-post")
        post_holder["post"] = post
        post_holder["post_prov"] = post_prov
        post_holder["popup_after"] = recognize_reset_popup(post.frame)
        post_holder["campaign_after"] = op.recognize(post.frame)
        still_popup = bool(post_holder["popup_after"].get("recognized"))
        tier_map = (
            post_holder["campaign_after"].observation.screen == CampaignScreen.TIER_MAP
        )
        return (
            _build_vip_reset_observation(
                frame=post.frame,
                frame_sha256=post.sha256,
                capture_completed_monotonic=post.captured_monotonic,
                target_roi=target_roi,
                overlay_state="none_observed" if (tier_map and not still_popup) else (
                    "known_reset_popup" if still_popup else "unknown"
                ),
                recognized=tier_map or still_popup,
                source_state=(
                    "CAMPAIGN_TIER_MAP"
                    if tier_map and not still_popup
                    else ("RESET_POPUP" if still_popup else "UNKNOWN")
                ),
                target_identity=None if (tier_map and not still_popup) else VIP_RESET_CLOSE_TARGET_IDENTITY,
            ),
        )

    def reconcile(_intent, item: Observation) -> bool:
        post = post_holder.get("post")
        popup_after = post_holder.get("popup_after") or {}
        campaign_after = post_holder.get("campaign_after")
        if post is None or campaign_after is None:
            return False
        return bool(
            vip_popup_handled(
                detail,
                popup_after,
                recognized_successor=(
                    campaign_after.observation.screen == CampaignScreen.TIER_MAP
                ),
            )
            and item.source_state == "CAMPAIGN_TIER_MAP"
        )

    try:
        result = op._execute_via_safe_action(
            observation=observation,
            action_key=action_key,
            semantic_action=VIP_RESET_DISMISS_SEMANTIC_ACTION,
            transport_fn=transport_fn,
            recapture_fn=recapture_fn,
            post_observe_fn=post_observe,
            reconcile_fn=reconcile,
        )
    except Exception as exc:
        post = post_holder.get("post")
        post_rel = _rel(op.session, post.path) if post is not None else None
        op._close_dispatch_exception(
            ordinal=ordinal,
            source_rel=source_rel,
            before_rel=fresh_rel,
            transport_rel=transport_rel,
            exc=exc,
            transport_gate=transport_gate,
            post_rel=post_rel,
        )
        return {
            "status": "unresolved" if (transport_gate["attempted"] or transport_gate["input_sent"]) else "blocked",
            "reason": f"vip_reset_dismiss_failed:{exc}",
            "transport_dispatched": bool(
                transport_gate["attempted"] or transport_gate["input_sent"]
            ),
            "before_rel": fresh_rel,
            "transport_rel": transport_rel,
            "post_rel": post_rel,
        }

    post = post_holder["post"]
    result_path = op.session / f"{action_key}-result.json"
    payload = {
        "status": "dismissed",
        "popup_absent": not bool(post_holder["popup_after"].get("recognized")),
        "successor": post_holder["campaign_after"].observation.screen.value,
        "safe_action_status": result.status.value,
        "vip_popup_input_count": op.vip_popup_input_count,
    }
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    evidence = NavigationEvidenceSequence(
        source_path=source_rel,
        immediate_before_path=fresh_rel,
        transport_record_path=transport_rel,
        immediate_post_path=_rel(op.session, post.path),
        semantic_result_path=_rel(op.session, result_path),
    )
    op.mark_terminal(
        ordinal,
        evidence=evidence,
        terminal="dismissed_vip_reset_popup",
        unresolved=False,
    )
    return {
        "status": "dismissed",
        "reason": "popup_absent_campaign_tier_map",
        "transport_dispatched": True,
        "before_rel": fresh_rel,
        "transport_rel": transport_rel,
        "post_rel": _rel(op.session, post.path),
        "result_rel": _rel(op.session, result_path),
        "vip_popup_input_count": op.vip_popup_input_count,
    }


def _require_survey_budget(flow: Mapping[str, Any]) -> None:
    pnsctl = _pnsctl()
    if int(flow.get("maximum_navigation_inputs") or 0) != ACTIVATED_TRANSPORT_INPUT_CEILING:
        raise pnsctl.OperatorError("Campaign atlas survey ceiling must be exactly 272")
    used = int(flow.get("navigation_inputs_used") or 0)
    if used != 0 and flow.get(
        "navigation_budget_disposition"
    ) == "explicitly_authorized_not_started":
        raise pnsctl.OperatorError("survey accounting is inconsistent before first input")
    if used < 0 or used > ACTIVATED_TRANSPORT_INPUT_CEILING:
        raise pnsctl.OperatorError("Campaign atlas survey navigation_inputs_used is out of range")
    if int(flow.get("maximum_live_attempts") or 0) != 1:
        raise pnsctl.OperatorError("Campaign atlas survey allows exactly one live session")
    attempts = list(flow.get("live_attempts") or [])
    if len(attempts) != 1:
        raise pnsctl.OperatorError(
            "Campaign atlas survey requires exactly one opened unfinished live attempt"
        )
    attempt = attempts[0]
    if not isinstance(attempt, Mapping):
        raise pnsctl.OperatorError("Campaign atlas survey live attempt is malformed")
    if attempt.get("finished_at") is not None or attempt.get("terminal_outcome") is not None:
        raise pnsctl.OperatorError("Campaign atlas survey session budget already consumed")


def _parse_prior_session_lifecycle(session: Path) -> dict[str, Any]:
    """Parse prior survey lifecycle into fail-closed category/terminal facts."""

    path = session / LIFECYCLE_PATH
    if not path.is_file():
        raise RuntimeError("prior survey lifecycle is missing")
    prepared_categories: dict[int, str] = {}
    input_sent: set[int] = set()
    terminals: dict[int, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        ordinal = int(event.get("input_ordinal") or 0)
        if ordinal <= 0:
            raise RuntimeError("prior survey lifecycle has a malformed input_ordinal")
        lifecycle = str(event.get("lifecycle") or "")
        if lifecycle == InputLifecycle.PREPARED.value:
            category = str(event.get("category") or "")
            if not category:
                raise RuntimeError("prior prepared lifecycle is missing category")
            prepared_categories[ordinal] = category
        elif lifecycle == InputLifecycle.INPUT_SENT.value:
            input_sent.add(ordinal)
        elif lifecycle in {InputLifecycle.TERMINAL.value, InputLifecycle.UNRESOLVED.value}:
            terminals[ordinal] = {
                "lifecycle": lifecycle,
                "terminal": str(event.get("terminal") or ""),
                "unresolved": bool(event.get("unresolved")),
            }
        else:
            raise RuntimeError(f"prior survey lifecycle has unsupported event: {lifecycle}")
    return {
        "prepared_categories": prepared_categories,
        "input_sent": input_sent,
        "terminals": terminals,
    }


def _count_journal_matching_auxiliary_terminals(
    session: Path, *, expected_terminal: str
) -> int:
    """Count closed journal AUXILIARY terminals with an exact terminal classification."""

    path = session / "journal.jsonl"
    if not path.is_file():
        return 0
    matched = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if str(entry.get("budget_category") or "") != KNOWN_CONTINUATION_PRIOR_CATEGORY.value:
            continue
        if str(entry.get("lifecycle") or "") != InputLifecycle.TERMINAL.value:
            raise RuntimeError("prior journal AUXILIARY entry is not terminal")
        if bool(entry.get("unresolved")):
            raise RuntimeError("prior journal AUXILIARY entry is unresolved")
        if str(entry.get("terminal_classification") or "") != expected_terminal:
            raise RuntimeError(
                "prior journal AUXILIARY terminal mismatch for known continuation: "
                f"expected={expected_terminal} got={entry.get('terminal_classification')}"
            )
        matched += 1
    return matched


def _verify_known_prior_auxiliary_session(
    session: Path, *, count: int, terminal: str, require_full_lifecycle: bool
) -> dict[str, Any]:
    """Independently verify one exact prior AUXILIARY evidence session."""

    if not session.is_dir():
        raise RuntimeError(
            "known prior survey session is missing for evidence-backed continuation: "
            f"{session.name}"
        )
    if survey_has_open_prepared_lifecycle(session):
        raise RuntimeError("prior survey has open prepared lifecycle; refuse continuation seed")
    durable = load_durable_survey_accounting(session)
    if bool(durable.get("unresolved")) or bool(durable.get("open_prepared")):
        raise RuntimeError("prior survey durable accounting is unresolved/open-prepared")
    accounting_payload = durable.get("accounting") or {}
    if int(accounting_payload.get("edge_clamp_used") or 0) != 0:
        raise RuntimeError("prior durable edge_clamp_used must be zero for known AUX continuation")
    if int(accounting_payload.get("overlap_used") or 0) != 0:
        raise RuntimeError("prior durable overlap_used must be zero for known AUX continuation")
    parsed = _parse_prior_session_lifecycle(session)
    prepared = parsed["prepared_categories"]
    sent = parsed["input_sent"]
    terminals = parsed["terminals"]
    matching_ordinals = [
        ordinal
        for ordinal, terminal_event in terminals.items()
        if str(terminal_event.get("terminal") or "") == terminal
    ]
    if len(matching_ordinals) != count:
        raise RuntimeError(
            "prior survey matching terminal count does not match known continuation count"
        )
    for ordinal in matching_ordinals:
        terminal_event = terminals[ordinal]
        if terminal_event["lifecycle"] != InputLifecycle.TERMINAL.value or terminal_event["unresolved"]:
            raise RuntimeError("prior survey input is not a closed terminal AUXILIARY")
    if require_full_lifecycle:
        if set(prepared) != sent or set(prepared) != set(terminals):
            raise RuntimeError("prior survey lifecycle prepared/input_sent/terminal sets disagree")
        if len(sent) != count:
            raise RuntimeError(
                "prior survey input_sent count does not match known continuation count"
            )
        for ordinal, category in prepared.items():
            if category != KNOWN_CONTINUATION_PRIOR_CATEGORY.value:
                raise RuntimeError(
                    f"prior survey input {ordinal} category={category} is not AUXILIARY; "
                    "refuse generic reinterpretation"
                )
            if terminals[ordinal]["terminal"] != terminal:
                raise RuntimeError(
                    "prior survey terminal mismatch for known continuation: "
                    f"expected={terminal} got={terminals[ordinal]['terminal']}"
                )
        if int(durable.get("transport_inputs_used") or 0) != count:
            raise RuntimeError("prior durable transport_inputs_used does not match known count")
        if int(accounting_payload.get("auxiliary_used") or 0) != count:
            raise RuntimeError("prior durable auxiliary_used does not match known AUXILIARY count")
    else:
        # Imported AUX terminals may omit prepared/input_sent; never count non-AUX
        # zero-transport history (for example edge-top-00) as seeded budget.
        for ordinal in sent:
            category = prepared.get(ordinal)
            if category is None:
                raise RuntimeError("prior survey input_sent lacks prepared category")
            if category != KNOWN_CONTINUATION_PRIOR_CATEGORY.value:
                raise RuntimeError(
                    f"prior survey input {ordinal} category={category} is not AUXILIARY; "
                    "refuse generic reinterpretation"
                )
        if sent and set(sent) != set(matching_ordinals):
            # INPUT_SENT may be absent for imported terminals; when present it must
            # match the accepted AUX set exactly (no edge/overlap transport).
            raise RuntimeError("prior survey input_sent set disagrees with accepted AUX terminals")
        journal_matched = _count_journal_matching_auxiliary_terminals(
            session, expected_terminal=terminal
        )
        if journal_matched != count:
            raise RuntimeError(
                "prior journal AUXILIARY terminal count does not match known continuation count"
            )
        session_sent = durable.get("session_navigation_inputs_sent")
        if session_sent is None:
            session_sent = durable.get("input_sent_count")
        if session_sent is None or int(session_sent) != count:
            raise RuntimeError(
                "prior durable session-sent count does not match known AUXILIARY count"
            )
        if int(accounting_payload.get("auxiliary_used") or 0) < count:
            raise RuntimeError("prior durable auxiliary_used cannot cover known AUXILIARY count")
    return {
        "session_id": session.name,
        "count": count,
        "terminal": terminal,
        "category": KNOWN_CONTINUATION_PRIOR_CATEGORY.value,
        "prior_session_directory": str(session).replace("\\", "/"),
    }


def resolve_evidence_backed_prior_auxiliary_seed(
    *,
    artifact_root: Path,
    claimed_navigation_inputs_used: int,
) -> tuple[InputBudgetAccounting, dict[str, Any]]:
    """Seed cumulative budget from exact known prior terminals.

    claimed=0 → empty. claimed=4 → AUX-only known sessions.
    claimed=5 → AUX 4 + exactly one reconciled EDGE_CLAMP progress, gated on an
    immutable offline reconciliation receipt (never speculative).
    claimed=91 → accepted traversal session accounting AUX5/EDGE24/OVERLAP62 with
    all inputs terminal and difficulty-tier-1 complete; resume at tier2 only.
    claimed=92 → accepted tier2 AUX terminal on top of that traversal evidence;
    resume at campaign-exit-home only.
    """

    claimed = int(claimed_navigation_inputs_used)
    empty_meta = {
        "prior_inputs_seeded": 0,
        "prior_auxiliary_seeded": 0,
        "prior_edge_clamp_seeded": 0,
        "prior_overlap_seeded": 0,
        "prior_session_id": None,
        "prior_session_ids": [],
        "prior_sessions": [],
        "prior_terminal": None,
        "prior_category": None,
        "prior_session_directory": None,
    }
    if claimed == 0:
        return InputBudgetAccounting(), empty_meta
    if claimed == KNOWN_CONTINUATION_PRIOR_COUNT:
        verified_sessions: list[dict[str, Any]] = []
        for item in KNOWN_CONTINUATION_PRIOR_EVIDENCE:
            session = Path(artifact_root) / FLOW_ID / str(item["session_id"])
            verified_sessions.append(
                _verify_known_prior_auxiliary_session(
                    session,
                    count=int(item["count"]),
                    terminal=str(item["terminal"]),
                    require_full_lifecycle=bool(item["require_full_lifecycle"]),
                )
            )
        if sum(int(item["count"]) for item in verified_sessions) != KNOWN_CONTINUATION_PRIOR_COUNT:
            raise RuntimeError("known prior session counts do not sum to continuation total")
        accounting = InputBudgetAccounting(auxiliary_used=KNOWN_CONTINUATION_PRIOR_COUNT)
        meta = {
            "prior_inputs_seeded": KNOWN_CONTINUATION_PRIOR_COUNT,
            "prior_auxiliary_seeded": KNOWN_CONTINUATION_PRIOR_COUNT,
            "prior_edge_clamp_seeded": 0,
            "prior_overlap_seeded": 0,
            "prior_session_ids": list(KNOWN_CONTINUATION_PRIOR_SESSION_IDS),
            "prior_sessions": verified_sessions,
            "prior_category": KNOWN_CONTINUATION_PRIOR_CATEGORY.value,
            # Multi-session seed: singular aliases remain unset to avoid false identity.
            "prior_session_id": None,
            "prior_terminal": None,
            "prior_session_directory": None,
        }
        return accounting, meta
    if claimed == KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE:
        aux_accounting, aux_meta = resolve_evidence_backed_prior_auxiliary_seed(
            artifact_root=artifact_root,
            claimed_navigation_inputs_used=KNOWN_CONTINUATION_PRIOR_COUNT,
        )
        edge_meta = _verify_reconciled_edge_continuation_session(
            Path(artifact_root)
            / FLOW_ID
            / str(KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE["session_id"])
        )
        accounting = InputBudgetAccounting(
            auxiliary_used=int(aux_accounting.auxiliary_used),
            edge_clamp_used=KNOWN_CONTINUATION_RECONCILED_EDGE_COUNT,
        )
        prior_sessions = list(aux_meta.get("prior_sessions") or []) + [edge_meta]
        prior_session_ids = list(aux_meta.get("prior_session_ids") or []) + [
            str(edge_meta["session_id"])
        ]
        meta = {
            "prior_inputs_seeded": KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE,
            "prior_auxiliary_seeded": KNOWN_CONTINUATION_PRIOR_COUNT,
            "prior_edge_clamp_seeded": KNOWN_CONTINUATION_RECONCILED_EDGE_COUNT,
            "prior_overlap_seeded": 0,
            "prior_session_ids": prior_session_ids,
            "prior_sessions": prior_sessions,
            "prior_category": KNOWN_CONTINUATION_MIXED_CATEGORY,
            "prior_session_id": None,
            "prior_terminal": None,
            "prior_session_directory": None,
            "reconciled_edge_session_id": str(edge_meta["session_id"]),
            "reconciled_edge_receipt": str(edge_meta["receipt_path"]),
            "reconciled_edge_action_key": str(edge_meta["action_key"]),
        }
        return accounting, meta
    if claimed == KNOWN_CONTINUATION_CUMULATIVE_WITH_TRAVERSAL:
        traversal_meta = _verify_accepted_traversal_continuation_session(
            Path(artifact_root)
            / FLOW_ID
            / str(KNOWN_CONTINUATION_TRAVERSAL_SESSION["session_id"])
        )
        accounting = InputBudgetAccounting(
            auxiliary_used=int(KNOWN_CONTINUATION_TRAVERSAL_SESSION["auxiliary_used"]),
            edge_clamp_used=int(KNOWN_CONTINUATION_TRAVERSAL_SESSION["edge_clamp_used"]),
            overlap_used=int(KNOWN_CONTINUATION_TRAVERSAL_SESSION["overlap_used"]),
        )
        meta = {
            "prior_inputs_seeded": KNOWN_CONTINUATION_CUMULATIVE_WITH_TRAVERSAL,
            "prior_auxiliary_seeded": int(
                KNOWN_CONTINUATION_TRAVERSAL_SESSION["auxiliary_used"]
            ),
            "prior_edge_clamp_seeded": int(
                KNOWN_CONTINUATION_TRAVERSAL_SESSION["edge_clamp_used"]
            ),
            "prior_overlap_seeded": int(
                KNOWN_CONTINUATION_TRAVERSAL_SESSION["overlap_used"]
            ),
            "prior_session_ids": list(KNOWN_CONTINUATION_TRAVERSAL_SESSION_IDS),
            "prior_sessions": [traversal_meta],
            "prior_category": KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY,
            "prior_session_id": str(KNOWN_CONTINUATION_TRAVERSAL_SESSION["session_id"]),
            "prior_terminal": "blocked_fail_closed_after_difficulty_tier_1",
            "prior_session_directory": str(traversal_meta["prior_session_directory"]),
            "resume_action_key": str(
                KNOWN_CONTINUATION_TRAVERSAL_SESSION["resume_action_key"]
            ),
            "completed_action_key": str(
                KNOWN_CONTINUATION_TRAVERSAL_SESSION["completed_action_key"]
            ),
            "skip_prior_action_keys": list(traversal_meta["skip_prior_action_keys"]),
            "retained_tier1_post_frame": str(
                KNOWN_CONTINUATION_TRAVERSAL_SESSION["retained_tier1_post_frame"]
            ),
            "retained_tier1_immediate_before_frame": str(
                KNOWN_CONTINUATION_TRAVERSAL_SESSION[
                    "retained_tier1_immediate_before_frame"
                ]
            ),
            "retained_tier1_post_sha256": str(traversal_meta["retained_tier1_post_sha256"]),
        }
        return accounting, meta
    if claimed == KNOWN_CONTINUATION_CUMULATIVE_WITH_TIER2_EXIT:
        # Keep traversal evidence gate; then verify the accepted tier2 AUX session.
        _verify_accepted_traversal_continuation_session(
            Path(artifact_root)
            / FLOW_ID
            / str(KNOWN_CONTINUATION_TRAVERSAL_SESSION["session_id"])
        )
        exit_meta = _verify_accepted_tier2_exit_continuation_session(
            Path(artifact_root)
            / FLOW_ID
            / str(KNOWN_CONTINUATION_TIER2_EXIT_SESSION["session_id"])
        )
        accounting = InputBudgetAccounting(
            auxiliary_used=int(KNOWN_CONTINUATION_TIER2_EXIT_SESSION["auxiliary_used"]),
            edge_clamp_used=int(KNOWN_CONTINUATION_TIER2_EXIT_SESSION["edge_clamp_used"]),
            overlap_used=int(KNOWN_CONTINUATION_TIER2_EXIT_SESSION["overlap_used"]),
        )
        meta = {
            "prior_inputs_seeded": KNOWN_CONTINUATION_CUMULATIVE_WITH_TIER2_EXIT,
            "prior_auxiliary_seeded": int(
                KNOWN_CONTINUATION_TIER2_EXIT_SESSION["auxiliary_used"]
            ),
            "prior_edge_clamp_seeded": int(
                KNOWN_CONTINUATION_TIER2_EXIT_SESSION["edge_clamp_used"]
            ),
            "prior_overlap_seeded": int(
                KNOWN_CONTINUATION_TIER2_EXIT_SESSION["overlap_used"]
            ),
            "prior_session_ids": list(KNOWN_CONTINUATION_EXIT_SESSION_IDS),
            "prior_sessions": [exit_meta],
            "prior_category": KNOWN_CONTINUATION_EXIT_RESUME_CATEGORY,
            "prior_session_id": str(KNOWN_CONTINUATION_TIER2_EXIT_SESSION["session_id"]),
            "prior_terminal": "blocked_fail_closed_after_difficulty_tier_2",
            "prior_session_directory": str(exit_meta["prior_session_directory"]),
            "resume_action_key": str(
                KNOWN_CONTINUATION_TIER2_EXIT_SESSION["resume_action_key"]
            ),
            "completed_action_key": str(
                KNOWN_CONTINUATION_TIER2_EXIT_SESSION["completed_action_key"]
            ),
            "skip_prior_action_keys": list(exit_meta["skip_prior_action_keys"]),
            "retained_traversal_session_id": str(
                KNOWN_CONTINUATION_TIER2_EXIT_SESSION["retained_traversal_session_id"]
            ),
            "retained_tier2_post_frame": str(
                KNOWN_CONTINUATION_TIER2_EXIT_SESSION["retained_tier2_post_frame"]
            ),
            "retained_tier2_post_sha256": str(exit_meta["retained_tier2_post_sha256"]),
            "retained_exit_immediate_before_frame": str(
                KNOWN_CONTINUATION_TIER2_EXIT_SESSION[
                    "retained_exit_immediate_before_frame"
                ]
            ),
        }
        return accounting, meta
    raise RuntimeError(
        "evidence-backed continuation accepts only claimed="
        f"{KNOWN_CONTINUATION_PRIOR_COUNT} (AUX) or "
        f"{KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE} "
        f"(AUX+reconciled EDGE) or "
        f"{KNOWN_CONTINUATION_CUMULATIVE_WITH_TRAVERSAL} "
        f"(traversal resume at difficulty-tier-2) or "
        f"{KNOWN_CONTINUATION_CUMULATIVE_WITH_TIER2_EXIT} "
        f"(exit-only after difficulty-tier-2); claimed={claimed}"
    )


def write_survey_continuation_reference(
    session: Path, continuation: Mapping[str, Any]
) -> str | None:
    """Retain an auditable reference to the prior session without mutating it."""

    if int(continuation.get("prior_inputs_seeded") or 0) <= 0:
        return None
    category = str(continuation.get("prior_category") or "")
    if category == KNOWN_CONTINUATION_EXIT_RESUME_CATEGORY:
        continuation_kind = "evidence_backed_traversal_resume_campaign_exit"
    elif category == KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY:
        continuation_kind = "evidence_backed_traversal_resume_difficulty_tier2"
    elif category == KNOWN_CONTINUATION_MIXED_CATEGORY:
        continuation_kind = "evidence_backed_prior_auxiliary_and_reconciled_edge"
    else:
        continuation_kind = "evidence_backed_prior_auxiliary"
    payload = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "continuation_kind": continuation_kind,
        **dict(continuation),
    }
    path = session / CONTINUATION_PATH
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return CONTINUATION_PATH


def _parse_edge_action_key(action_key: str) -> tuple[str, int]:
    """Parse ``edge-{direction}-{step:02d}`` into (direction, step)."""

    parts = str(action_key or "").split("-")
    if len(parts) != 3 or parts[0] != "edge":
        raise RuntimeError(f"edge action_key is malformed: {action_key}")
    direction = parts[1]
    if direction not in _DIRECTIONS:
        raise RuntimeError(f"edge action_key direction is unsupported: {action_key}")
    try:
        step = int(parts[2])
    except ValueError as exc:
        raise RuntimeError(f"edge action_key step is malformed: {action_key}") from exc
    if step < 0 or step >= ACTIVATED_EDGE_STEPS_PER_DIRECTION:
        raise RuntimeError(f"edge action_key step is out of range: {action_key}")
    return direction, step


def resolve_reconciled_edge_coverage_resume(
    continuation: Mapping[str, Any],
    *,
    current_screen: CampaignScreen,
) -> dict[str, Any]:
    """Resume edge coverage after reconciled EDGE seed without re-dispatching it.

    Requires confirmed receipt identity in the continuation seed and a current
    TIER_MAP screen. Fail-closed when progress state cannot be established.
    """

    empty = {
        "required": False,
        "edge_start_step_by_direction": {direction: 0 for direction in _DIRECTIONS},
        "reconciled_action_key": None,
        "next_action_key": None,
        "prior_progress_swipe": None,
        "direction": None,
    }
    category = str(continuation.get("prior_category") or "")
    if category in {
        KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY,
        KNOWN_CONTINUATION_EXIT_RESUME_CATEGORY,
    }:
        return empty
    prior_edge = int(continuation.get("prior_edge_clamp_seeded") or 0)
    if category != KNOWN_CONTINUATION_MIXED_CATEGORY and prior_edge <= 0:
        return empty
    if category != KNOWN_CONTINUATION_MIXED_CATEGORY:
        raise RuntimeError(
            "reconciled EDGE resume requires mixed_auxiliary_and_edge_clamp continuation"
        )
    if prior_edge != KNOWN_CONTINUATION_RECONCILED_EDGE_COUNT:
        raise RuntimeError("reconciled EDGE resume prior_edge_clamp_seeded mismatch")
    if int(continuation.get("prior_inputs_seeded") or 0) != (
        KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE
    ):
        raise RuntimeError("reconciled EDGE resume prior_inputs_seeded mismatch")
    action_key = str(continuation.get("reconciled_edge_action_key") or "")
    receipt = str(continuation.get("reconciled_edge_receipt") or "")
    session_id = str(continuation.get("reconciled_edge_session_id") or "")
    if not action_key or not receipt or not session_id:
        raise RuntimeError(
            "continuation progress state cannot be established: missing reconciled "
            "EDGE action_key/receipt/session identity"
        )
    expected = KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE
    if action_key != str(expected["action_key"]):
        raise RuntimeError("reconciled EDGE resume action_key mismatch")
    if receipt != str(expected["receipt_name"]):
        raise RuntimeError("reconciled EDGE resume receipt mismatch")
    if session_id != str(expected["session_id"]):
        raise RuntimeError("reconciled EDGE resume session_id mismatch")
    if current_screen != CampaignScreen.TIER_MAP:
        raise RuntimeError(
            "reconciled EDGE continuation requires current CAMPAIGN_TIER_MAP; "
            "refuse Home re-entry that would discard viewport progress or "
            "re-dispatch the reconciled edge action"
        )
    direction, step = _parse_edge_action_key(action_key)
    next_step = step + 1
    if next_step >= ACTIVATED_EDGE_STEPS_PER_DIRECTION:
        raise RuntimeError(
            f"reconciled EDGE {action_key} leaves no remaining steps in {direction}"
        )
    next_action_key = f"edge-{direction}-{next_step:02d}"
    if next_action_key == action_key:
        raise RuntimeError("next edge action_key must be distinct from reconciled action")
    starts = {item: 0 for item in _DIRECTIONS}
    starts[direction] = next_step
    swipe = hud_safe_pan_gesture(direction).as_swipe()
    return {
        "required": True,
        "edge_start_step_by_direction": starts,
        "reconciled_action_key": action_key,
        "next_action_key": next_action_key,
        "prior_progress_swipe": swipe,
        "direction": direction,
    }


def resolve_difficulty_tier2_coverage_resume(
    continuation: Mapping[str, Any],
    *,
    current_screen: CampaignScreen,
) -> dict[str, Any]:
    """Resume after accepted traversal seed at difficulty-tier-2 only."""

    empty = {
        "required": False,
        "resume_action_key": None,
        "skip_prior_action_keys": (),
        "retained_tier1_post_frame": None,
        "retained_tier1_post_sha256": None,
        "prior_session_directory": None,
    }
    category = str(continuation.get("prior_category") or "")
    if category != KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY:
        return empty
    if int(continuation.get("prior_inputs_seeded") or 0) != (
        KNOWN_CONTINUATION_CUMULATIVE_WITH_TRAVERSAL
    ):
        raise RuntimeError("difficulty-tier2 resume prior_inputs_seeded mismatch")
    resume_key = str(continuation.get("resume_action_key") or "")
    completed_key = str(continuation.get("completed_action_key") or "")
    if resume_key != str(KNOWN_CONTINUATION_TRAVERSAL_SESSION["resume_action_key"]):
        raise RuntimeError("difficulty-tier2 resume action_key mismatch")
    if completed_key != str(KNOWN_CONTINUATION_TRAVERSAL_SESSION["completed_action_key"]):
        raise RuntimeError("difficulty-tier2 completed action_key mismatch")
    if current_screen != CampaignScreen.TIER_MAP:
        raise RuntimeError(
            "difficulty-tier2 continuation requires current CAMPAIGN_TIER_MAP; "
            "refuse Home re-entry that would reissue edge/overlap/tier1"
        )
    skip_keys = tuple(str(item) for item in (continuation.get("skip_prior_action_keys") or ()))
    if not skip_keys:
        raise RuntimeError("difficulty-tier2 resume missing skip_prior_action_keys")
    if completed_key not in skip_keys:
        raise RuntimeError("difficulty-tier2 resume must skip completed difficulty-tier-1")
    if resume_key in skip_keys:
        raise RuntimeError("difficulty-tier2 resume action cannot be in skip set")
    for forbidden_prefix in ("edge-", "overlap-"):
        if not any(key.startswith(forbidden_prefix) for key in skip_keys):
            raise RuntimeError(
                f"difficulty-tier2 resume skip set missing {forbidden_prefix}* keys"
            )
    return {
        "required": True,
        "resume_action_key": resume_key,
        "skip_prior_action_keys": skip_keys,
        "retained_tier1_post_frame": str(
            continuation.get("retained_tier1_post_frame") or ""
        ),
        "retained_tier1_post_sha256": str(
            continuation.get("retained_tier1_post_sha256") or ""
        ),
        "prior_session_directory": str(
            continuation.get("prior_session_directory") or ""
        ),
    }


def resolve_campaign_exit_only_resume(
    continuation: Mapping[str, Any],
    *,
    current_screen: CampaignScreen,
) -> dict[str, Any]:
    """Resume after accepted tier2 seed at campaign-exit-home only."""

    empty = {
        "required": False,
        "resume_action_key": None,
        "skip_prior_action_keys": (),
        "prior_session_directory": None,
        "retained_traversal_session_id": None,
        "retained_tier2_post_frame": None,
        "retained_tier2_post_sha256": None,
    }
    category = str(continuation.get("prior_category") or "")
    if category != KNOWN_CONTINUATION_EXIT_RESUME_CATEGORY:
        return empty
    if int(continuation.get("prior_inputs_seeded") or 0) != (
        KNOWN_CONTINUATION_CUMULATIVE_WITH_TIER2_EXIT
    ):
        raise RuntimeError("campaign-exit resume prior_inputs_seeded mismatch")
    resume_key = str(continuation.get("resume_action_key") or "")
    completed_key = str(continuation.get("completed_action_key") or "")
    if resume_key != str(KNOWN_CONTINUATION_TIER2_EXIT_SESSION["resume_action_key"]):
        raise RuntimeError("campaign-exit resume action_key mismatch")
    if completed_key != str(KNOWN_CONTINUATION_TIER2_EXIT_SESSION["completed_action_key"]):
        raise RuntimeError("campaign-exit completed action_key mismatch")
    if current_screen != CampaignScreen.TIER_MAP:
        raise RuntimeError(
            "campaign-exit continuation requires current CAMPAIGN_TIER_MAP with "
            "tier2 selected; refuse Home re-entry that would reissue prior keys"
        )
    skip_keys = tuple(str(item) for item in (continuation.get("skip_prior_action_keys") or ()))
    if not skip_keys:
        raise RuntimeError("campaign-exit resume missing skip_prior_action_keys")
    if completed_key not in skip_keys:
        raise RuntimeError("campaign-exit resume must skip completed difficulty-tier-2")
    if "difficulty-tier-1" not in skip_keys:
        raise RuntimeError("campaign-exit resume must skip difficulty-tier-1")
    if resume_key in skip_keys:
        raise RuntimeError("campaign-exit resume action cannot be in skip set")
    for forbidden_prefix in ("edge-", "overlap-"):
        if not any(key.startswith(forbidden_prefix) for key in skip_keys):
            raise RuntimeError(
                f"campaign-exit resume skip set missing {forbidden_prefix}* keys"
            )
    return {
        "required": True,
        "resume_action_key": resume_key,
        "skip_prior_action_keys": skip_keys,
        "prior_session_directory": str(
            continuation.get("prior_session_directory") or ""
        ),
        "retained_traversal_session_id": str(
            continuation.get("retained_traversal_session_id") or ""
        ),
        "retained_tier2_post_frame": str(
            continuation.get("retained_tier2_post_frame") or ""
        ),
        "retained_tier2_post_sha256": str(
            continuation.get("retained_tier2_post_sha256") or ""
        ),
    }


def _prior_seed_category_breakdown(
    continuation: Mapping[str, Any], *, prior: int
) -> tuple[int, int, int]:
    """Return (prior_auxiliary, prior_edge_clamp, prior_overlap) for an evidence-backed seed."""

    category = str(continuation.get("prior_category") or "")
    if category == KNOWN_CONTINUATION_PRIOR_CATEGORY.value:
        if prior != KNOWN_CONTINUATION_PRIOR_COUNT:
            raise RuntimeError("AUXILIARY prior seed count mismatch")
        return prior, 0, 0
    if category == KNOWN_CONTINUATION_MIXED_CATEGORY:
        prior_aux = int(continuation.get("prior_auxiliary_seeded") or 0)
        prior_edge = int(continuation.get("prior_edge_clamp_seeded") or 0)
        prior_overlap = int(continuation.get("prior_overlap_seeded") or 0)
        if prior_aux != KNOWN_CONTINUATION_PRIOR_COUNT:
            raise RuntimeError("mixed prior auxiliary seed count mismatch")
        if prior_edge != KNOWN_CONTINUATION_RECONCILED_EDGE_COUNT:
            raise RuntimeError("mixed prior edge-clamp seed count mismatch")
        if prior_overlap != 0:
            raise RuntimeError("mixed AUX+EDGE prior must not seed overlap")
        if prior_aux + prior_edge + prior_overlap != prior:
            raise RuntimeError("mixed prior seed parts do not sum to prior_inputs_seeded")
        if prior != KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE:
            raise RuntimeError("mixed prior seed total mismatch")
        return prior_aux, prior_edge, prior_overlap
    if category == KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY:
        prior_aux = int(continuation.get("prior_auxiliary_seeded") or 0)
        prior_edge = int(continuation.get("prior_edge_clamp_seeded") or 0)
        prior_overlap = int(continuation.get("prior_overlap_seeded") or 0)
        expected = KNOWN_CONTINUATION_TRAVERSAL_SESSION
        if prior_aux != int(expected["auxiliary_used"]):
            raise RuntimeError("traversal prior auxiliary seed count mismatch")
        if prior_edge != int(expected["edge_clamp_used"]):
            raise RuntimeError("traversal prior edge-clamp seed count mismatch")
        if prior_overlap != int(expected["overlap_used"]):
            raise RuntimeError("traversal prior overlap seed count mismatch")
        if prior_aux + prior_edge + prior_overlap != prior:
            raise RuntimeError("traversal prior seed parts do not sum to prior_inputs_seeded")
        if prior != KNOWN_CONTINUATION_CUMULATIVE_WITH_TRAVERSAL:
            raise RuntimeError("traversal prior seed total mismatch")
        return prior_aux, prior_edge, prior_overlap
    if category == KNOWN_CONTINUATION_EXIT_RESUME_CATEGORY:
        prior_aux = int(continuation.get("prior_auxiliary_seeded") or 0)
        prior_edge = int(continuation.get("prior_edge_clamp_seeded") or 0)
        prior_overlap = int(continuation.get("prior_overlap_seeded") or 0)
        expected = KNOWN_CONTINUATION_TIER2_EXIT_SESSION
        if prior_aux != int(expected["auxiliary_used"]):
            raise RuntimeError("exit prior auxiliary seed count mismatch")
        if prior_edge != int(expected["edge_clamp_used"]):
            raise RuntimeError("exit prior edge-clamp seed count mismatch")
        if prior_overlap != int(expected["overlap_used"]):
            raise RuntimeError("exit prior overlap seed count mismatch")
        if prior_aux + prior_edge + prior_overlap != prior:
            raise RuntimeError("exit prior seed parts do not sum to prior_inputs_seeded")
        if prior != KNOWN_CONTINUATION_CUMULATIVE_WITH_TIER2_EXIT:
            raise RuntimeError("exit prior seed total mismatch")
        return prior_aux, prior_edge, prior_overlap
    raise RuntimeError(
        "session-scoped report accounting accepts only evidence-backed AUXILIARY, "
        "mixed AUX+reconciled-EDGE, traversal difficulty-tier2, or exit-only prior seed"
    )


def _session_scoped_report_accounting(state: "_SurveyState") -> InputBudgetAccounting:
    """Journal-aligned session accounting for SurveySessionReport packaging.

    Continuation keeps cumulative budget on ``state.accounting`` / delivery result.
    Report accounting must equal ``len(journal)`` and exclude the evidence-backed
    prior seed (never fabricate a current-session journal row for that prior).
    """

    prior = int(getattr(state, "prior_inputs_seeded", 0) or 0)
    cumulative = state.accounting
    if prior <= 0:
        return cumulative
    continuation = dict(getattr(state, "prior_continuation", {}) or {})
    if int(continuation.get("prior_inputs_seeded") or 0) != prior:
        raise RuntimeError("prior_continuation seed count disagrees with prior_inputs_seeded")
    prior_aux, prior_edge, prior_overlap = _prior_seed_category_breakdown(
        continuation, prior=prior
    )
    if int(cumulative.auxiliary_used) < prior_aux:
        raise RuntimeError("cumulative auxiliary_used cannot cover evidence-backed prior seed")
    if int(cumulative.edge_clamp_used) < prior_edge:
        raise RuntimeError("cumulative edge_clamp_used cannot cover evidence-backed prior seed")
    if int(cumulative.overlap_used) < prior_overlap:
        raise RuntimeError("cumulative overlap_used cannot cover evidence-backed prior seed")
    session_accounting = InputBudgetAccounting(
        edge_clamp_used=int(cumulative.edge_clamp_used) - prior_edge,
        overlap_used=int(cumulative.overlap_used) - prior_overlap,
        auxiliary_used=int(cumulative.auxiliary_used) - prior_aux,
        maximum_edge_clamp=int(cumulative.maximum_edge_clamp),
        maximum_overlap=int(cumulative.maximum_overlap),
        maximum_auxiliary=int(cumulative.maximum_auxiliary),
    )
    if session_accounting.transport_inputs_used != len(state.journal):
        raise RuntimeError(
            "session-scoped report accounting must equal current-session journal length"
        )
    if session_accounting.transport_inputs_used + prior != cumulative.transport_inputs_used:
        raise RuntimeError(
            "session report inputs + prior seed must equal cumulative navigation inputs"
        )
    # Journal category totals must match the session-scoped partition.
    edge = overlap = auxiliary = 0
    for entry in state.journal:
        if entry.budget_category is InputBudgetCategory.EDGE_CLAMP:
            edge += 1
        elif entry.budget_category is InputBudgetCategory.OVERLAP:
            overlap += 1
        elif entry.budget_category is InputBudgetCategory.AUXILIARY:
            auxiliary += 1
        else:
            raise RuntimeError("unknown journal budget category in session report accounting")
    if (
        edge != session_accounting.edge_clamp_used
        or overlap != session_accounting.overlap_used
        or auxiliary != session_accounting.auxiliary_used
    ):
        raise RuntimeError(
            "session-scoped report category totals disagree with current-session journal"
        )
    return session_accounting


def _seeded_complete_accounting_reconciles(
    *,
    report_accounting: InputBudgetAccounting,
    delivery_accounting: Mapping[str, Any],
    prior_continuation: Mapping[str, Any],
    cumulative_used: int,
    session_sent: int,
) -> bool:
    """Prove session report + evidence-backed prior seed == cumulative delivery."""

    prior_seeded = int(prior_continuation.get("prior_inputs_seeded") or 0)
    if prior_seeded <= 0:
        return False
    try:
        prior_aux, prior_edge, prior_overlap = _prior_seed_category_breakdown(
            prior_continuation, prior=prior_seeded
        )
    except RuntimeError:
        return False
    if report_accounting.transport_inputs_used != session_sent:
        return False
    if report_accounting.transport_inputs_used + prior_seeded != cumulative_used:
        return False
    if int(delivery_accounting.get("transport_inputs_used") or 0) != cumulative_used:
        return False
    if int(delivery_accounting.get("maximum_transport_inputs") or 0) != ACTIVATED_TRANSPORT_INPUT_CEILING:
        return False
    if report_accounting.maximum_transport_inputs != ACTIVATED_TRANSPORT_INPUT_CEILING:
        return False
    if int(delivery_accounting.get("edge_clamp_used") or 0) != (
        report_accounting.edge_clamp_used + prior_edge
    ):
        return False
    if int(delivery_accounting.get("overlap_used") or 0) != (
        report_accounting.overlap_used + prior_overlap
    ):
        return False
    if int(delivery_accounting.get("auxiliary_used") or 0) != (
        report_accounting.auxiliary_used + prior_aux
    ):
        return False
    return True


def assert_swipe_not_blind_retry(
    *,
    swipe: tuple[int, int, int, int, int] | None,
    last_swipe: tuple[int, int, int, int, int] | None,
    prior_progress_proven: bool,
) -> None:
    """Repeated geometry allowed only when prior post proved material map progress."""

    if swipe is None or last_swipe is None:
        return
    if swipe != last_swipe:
        return
    if prior_progress_proven:
        return
    raise RuntimeError("identical blind retry is prohibited")


def require_bound_survey_target(
    recognition: Any, identity: str, *, frame: np.ndarray | None = None
) -> tuple[int, int, int, int]:
    """Fail closed unless identity is bound by current-frame template measurement.

    Authority is measurement provenance from ``measured_survey_target``, not
    inequality versus historical compile-time HUD boxes. Recognition targets and
    static/base-request fallbacks never authorize binding.
    """

    del recognition  # recognizer/static ROI path is never authoritative
    if identity == "campaign-base-request":
        raise RuntimeError(
            "campaign-base-request static/base-request fallback is prohibited; "
            "use measured campaign-exit-base"
        )
    if survey_target_is_consequential(identity):
        raise RuntimeError(f"consequential target prohibited for survey: {identity}")
    if frame is None:
        raise RuntimeError("current native frame is required for measured target binding")
    roi, _score = measured_survey_target(frame, identity)
    return roi


def require_stable_survey_tap_rebound(
    *,
    proposal_roi: tuple[int, int, int, int],
    rebound_roi: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Fail closed before transport when fresh rebound drifts from proposal target_roi."""

    if rebound_roi != proposal_roi:
        raise RuntimeError(
            "survey tap immediate-before unstable/current-target-moved; zero transport"
        )
    return rebound_roi


# Test / helper aliases for strong spatial OCR binding.
_chapter_roi_from_recognition = chapter_roi_from_strong_spatial_evidence
_prison_trial_roi_from_hits = prison_trial_roi_from_strong_spatial_evidence


def reject_direct_survey_transport(*, authorized_token: object) -> None:
    if authorized_token is not _SURVEY_TRANSPORT_SEAL:
        raise RuntimeError("DIRECT_TRANSPORT_BYPASS_REJECTED")


def survey_has_open_prepared_lifecycle(session: Path) -> bool:
    """True when a prepared action may have transported without durable input_sent."""

    path = session / LIFECYCLE_PATH
    if not path.is_file():
        return False
    open_prepared: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        ordinal = int(event.get("input_ordinal") or 0)
        lifecycle = str(event.get("lifecycle") or "")
        if lifecycle == InputLifecycle.PREPARED.value:
            open_prepared.add(ordinal)
        elif lifecycle in {
            InputLifecycle.INPUT_SENT.value,
            InputLifecycle.TERMINAL.value,
            InputLifecycle.UNRESOLVED.value,
        }:
            open_prepared.discard(ordinal)
    return bool(open_prepared)


@dataclass
class _SurveyState:
    accounting: InputBudgetAccounting
    journal: list[NavigationJournalEntry] = field(default_factory=list)
    accepted: list[FrameClassification] = field(default_factory=list)
    rejected: list[FrameClassification] = field(default_factory=list)
    edge_clamps: list[EdgeClampReport] = field(default_factory=list)
    overlaps: list[OverlapAssociationReport] = field(default_factory=list)
    residuals: list[Any] = field(default_factory=list)
    landmarks: list[LandmarkBindingReport] = field(default_factory=list)
    coverage_gaps: list[CoverageGapReport] = field(default_factory=list)
    annotation_paths: list[str] = field(default_factory=list)
    last_swipe: tuple[int, int, int, int, int] | None = None
    last_progress_proven: bool = False
    loop_closure: LoopClosureReport | None = None
    cross_difficulty: CrossDifficultyGeometryReport | None = None
    safe_terminal: SafeTerminalReport | None = None
    capture_ordinal: int = 0
    unresolved: bool = False
    transport_dispatched: bool = False
    prior_inputs_seeded: int = 0
    prior_continuation: dict[str, Any] = field(default_factory=dict)

    @property
    def session_navigation_inputs_sent(self) -> int:
        return max(0, int(self.accounting.transport_inputs_used) - int(self.prior_inputs_seeded))

    @property
    def cumulative_navigation_inputs_used(self) -> int:
        return int(self.accounting.transport_inputs_used)


def _provenance_for(
    path: Path,
    *,
    session_id: str,
    ordinal: int,
    monotonic: float,
    transport_digest: str,
    semantic_digest: str,
    width: int,
    height: int,
) -> NativeFrameProvenance:
    return NativeFrameProvenance(
        source_id=str(path.as_posix()),
        capture_kind="live",
        runtime_session_id=session_id,
        capture_ordinal=ordinal,
        capture_completed_monotonic=monotonic,
        transport_sha256=transport_digest,
        semantic_sha256=semantic_digest,
        captured_at_utc=_utc_now(),
        width=width,
        height=height,
        profile_id=CAMPAIGN_PROFILE_ID,
        platform=CAMPAIGN_PLATFORM,
        package=CAMPAIGN_PACKAGE,
    )


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True, default=str) + "\n")


def _count_session_lifecycle_input_sent(session: Path) -> int:
    """Count INPUT_SENT ordinals in this session's lifecycle only (never prior seed)."""

    path = session / LIFECYCLE_PATH
    if not path.is_file():
        return 0
    sent_ordinals: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if str(event.get("lifecycle") or "") == InputLifecycle.INPUT_SENT.value:
            ordinal = int(event.get("input_ordinal") or 0)
            if ordinal > 0:
                sent_ordinals.add(ordinal)
    return len(sent_ordinals)


def _count_durable_input_sent(session: Path, state: "_SurveyState") -> int:
    """Cumulative budget: seeded prior + this session's durable INPUT_SENT / recorded used."""

    recorded = int(state.accounting.transport_inputs_used)
    session_sent = _count_session_lifecycle_input_sent(session)
    seeded = int(getattr(state, "prior_inputs_seeded", 0) or 0)
    return max(recorded, seeded + session_sent)


def _write_accounting(session: Path, state: "_SurveyState") -> None:
    used = _count_durable_input_sent(session, state)
    session_nav = int(getattr(state, "session_navigation_inputs_sent", 0) or 0)
    session_sent = max(_count_session_lifecycle_input_sent(session), session_nav)
    open_prepared = any(entry.lifecycle is InputLifecycle.PREPARED for entry in state.journal)
    payload = {
        "transport_inputs_used": used,
        "accounting": state.accounting.to_dict(),
        "unresolved": state.unresolved or open_prepared,
        # Current-session transport only — never inflate from cumulative/seeded used.
        "transport_dispatched": bool(state.transport_dispatched) or session_sent > 0,
        "open_prepared": open_prepared,
        "journal_len": len(state.journal),
        "input_sent_count": session_sent,
        "session_navigation_inputs_sent": session_sent,
        "prior_inputs_seeded": int(getattr(state, "prior_inputs_seeded", 0) or 0),
        "updated_at_utc": _utc_now(),
    }
    (session / ACCOUNTING_PATH).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_durable_survey_accounting(session: Path) -> dict[str, Any]:
    path = session / ACCOUNTING_PATH
    if not path.is_file():
        return {
            "transport_inputs_used": 0,
            "unresolved": False,
            "transport_dispatched": False,
            "journal_len": 0,
            "open_prepared": False,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if survey_has_open_prepared_lifecycle(session):
        payload["unresolved"] = True
        payload["open_prepared"] = True
        # Prepared may have transported; never treat as proven zero-input.
        payload["transport_dispatched"] = True
    return payload


def _rel(session: Path, path: Path) -> str:
    try:
        return str(path.relative_to(session)).replace("\\", "/")
    except ValueError:
        return path.name


def _ocr_hits(frame: np.ndarray) -> dict[str, tuple[int, int, int, int]]:
    left, top, right, bottom = MAP_SEARCH_ROI
    crop = frame[top:bottom, left:right]
    try:
        import pytesseract
    except ImportError:
        return {}
    payload = pytesseract.image_to_data(crop, output_type=pytesseract.Output.DICT)
    hits: dict[str, tuple[int, int, int, int]] = {}
    for index, text in enumerate(payload.get("text", [])):
        cleaned = str(text or "").strip()
        if not cleaned:
            continue
        x = left + int(payload["left"][index])
        y = top + int(payload["top"][index])
        w = max(1, int(payload["width"][index]))
        h = max(1, int(payload["height"][index]))
        hits[cleaned] = (x, y, x + w, y + h)
    return hits


def _annotate_roi(
    session: Path,
    frame: np.ndarray,
    *,
    label: str,
    roi: tuple[int, int, int, int],
    digest: str,
) -> str:
    annotated = frame.copy()
    x0, y0, x1, y1 = roi
    cv2.rectangle(annotated, (x0, y0), (x1, y1), (0, 255, 255), 2)
    cv2.putText(
        annotated,
        label[:48],
        (max(0, x0), max(20, y0 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 255, 255),
        1,
        cv2.LINE_AA,
    )
    out_dir = session / "annotations"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{label.replace(' ', '_')}-{digest[:12]}.png"
    cv2.imwrite(str(out), annotated)
    meta = {
        "label": label,
        "roi": list(roi),
        "source_sha256": digest,
        "annotation_path": _rel(session, out),
    }
    (out.with_suffix(".json")).write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return _rel(session, out)


def count_home_entry_transports(entry: Mapping[str, Any]) -> int:
    """Count exact Home-to-Campaign transport records (pans + open tap)."""

    records = entry.get("records") or []
    pans = sum(1 for item in records if str(item.get("disposition", "")).casefold() == "pan")
    opened = 1 if entry.get("status") == "opened" else 0
    total = pans + opened
    if total < 1:
        raise RuntimeError("Home-to-Campaign entry produced no countable transport records")
    return total


def _budget_has_capacity(accounting: InputBudgetAccounting, category: InputBudgetCategory) -> bool:
    try:
        accounting.record(category)
    except ValueError:
        return False
    return True


def _write_frame_classification_artifact(session: Path, state: "_SurveyState") -> str:
    payload = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "accepted_frames": [item.to_dict() for item in state.accepted],
        "rejected_frames": [item.to_dict() for item in state.rejected],
        "accepted_count": len(state.accepted),
        "rejected_count": len(state.rejected),
    }
    path = session / FRAME_CLASSIFICATION_PATH
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return _rel(session, path)


def _build_survey_observation(
    *,
    frame_sha256: str,
    capture_completed_monotonic: float,
    target_identity: str,
    target_roi: tuple[int, int, int, int],
    semantic_action: str,
    expected_postcondition: str,
) -> Observation:
    return Observation(
        frame_sha256=frame_sha256,
        capture_completed_monotonic=float(capture_completed_monotonic),
        runtime_profile_id=CAMPAIGN_PROFILE_ID,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="CAMPAIGN_TIER_MAP",
        overlay_state="none_observed",
        target_identity=target_identity,
        target_roi=target_roi,
        recognized=True,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition=expected_postcondition,
        evidence_refs=(f"campaign-atlas:{semantic_action}",),
        package_foreground=True,
        os_surface=False,
        hard_stop_detected=False,
    )


def _build_survey_policy_request(
    *,
    observation: Observation,
    action_id: str,
    action_key: str,
    lease_owner: str,
    navigation_session_id: str,
    monotonic_now: float,
    semantic_action: str,
) -> PolicyRequest:
    return PolicyRequest(
        action_id=action_id,
        action_key=action_key,
        task_id=FLOW_ID,
        task_mode="supervised_validation",
        semantic_action=semantic_action,
        expected_runtime_profile_id=CAMPAIGN_PROFILE_ID,
        observation=observation,
        monotonic_now=float(monotonic_now),
        observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=15.0,
        lease_owner=lease_owner,
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        action_class=ActionClass.NAVIGATION_ONLY,
        runtime_session_id=navigation_session_id,
    )


class _SurveyOperator:
    def __init__(
        self,
        session: Path,
        runtime: LocalBlueStacksRuntime,
        session_id: str,
        *,
        lease_owner: str,
        prior_accounting: InputBudgetAccounting | None = None,
        prior_continuation: Mapping[str, Any] | None = None,
    ) -> None:
        self.session = session
        self.runtime = runtime
        self.session_id = session_id
        self.lease_owner = lease_owner
        self.backend = OrbTranslationBackend()
        continuation = dict(prior_continuation or {})
        seeded = int(continuation.get("prior_inputs_seeded") or 0)
        accounting = prior_accounting if prior_accounting is not None else InputBudgetAccounting()
        if seeded != int(accounting.transport_inputs_used):
            raise RuntimeError(
                "prior continuation seed count must match seeded InputBudgetAccounting"
            )
        self.state = _SurveyState(
            accounting=accounting,
            prior_inputs_seeded=seeded,
            prior_continuation=continuation,
        )
        self.lifecycle_path = session / LIFECYCLE_PATH
        self.journal_path = session / "journal.jsonl"
        self.events_path = session / "events.jsonl"
        self.policy = CentralPolicy(supervised_tasks=frozenset({FLOW_ID, "MVP-QUEST-TO-CLAIM"}))
        self.store = SafetyStore(session / "campaign-atlas-survey-safety.sqlite3")
        self.store.acquire_lease(lease_owner, time.time(), 3600.0)
        self.vip_popup_input_count = 0
        for path in (
            self.lifecycle_path,
            self.journal_path,
            self.events_path,
            session / "ledger.jsonl",
            session / "capability-audit.jsonl",
        ):
            if not path.exists():
                path.write_text("", encoding="utf-8")
        write_survey_continuation_reference(session, continuation)
        _write_accounting(session, self.state)

    def close(self) -> None:
        self.store.close()

    def capture(self, label: str):
        frame = self.runtime.capture(label)
        self.state.capture_ordinal += 1
        height, width = frame.frame.shape[:2]
        # transport/file sha = PNG payload hash; semantic = frame_digest(decoded BGR).
        prov = _provenance_for(
            frame.path,
            session_id=self.session_id,
            ordinal=self.state.capture_ordinal,
            monotonic=frame.captured_monotonic,
            transport_digest=frame.sha256,
            semantic_digest=frame_digest(frame.frame),
            width=int(width),
            height=int(height),
        )
        self.state.accepted.append(
            FrameClassification(
                disposition=FrameDisposition.ACCEPTED,
                provenance=prov,
                mask_contract_id=MASK_CONTRACT_ID,
            )
        )
        return frame, prov

    def recognize(self, frame: np.ndarray):
        return recognize_campaign_frame(frame, _CLASSIFIER_STAGE)

    def _persist_lifecycle(self, event: Mapping[str, Any]) -> None:
        _append_jsonl(self.lifecycle_path, event)
        _write_accounting(self.session, self.state)

    def prepare_input(
        self,
        *,
        phase: SurveyPhase,
        category: InputBudgetCategory,
        before_rel: str,
        transport_rel: str,
        source_rel: str,
        swipe: tuple[int, int, int, int, int] | None,
        prior_progress_proven: bool,
        planned_terminal: str,
    ) -> int:
        assert_swipe_not_blind_retry(
            swipe=swipe,
            last_swipe=self.state.last_swipe,
            prior_progress_proven=prior_progress_proven,
        )
        if not _budget_has_capacity(self.state.accounting, category):
            raise RuntimeError(f"survey budget exhausted before dispatch: {category.value}")
        ordinal = len(self.state.journal) + 1
        evidence = NavigationEvidenceSequence(
            source_path=source_rel,
            immediate_before_path=before_rel,
            transport_record_path=transport_rel,
            immediate_post_path=before_rel,
            semantic_result_path=transport_rel,
        )
        entry = NavigationJournalEntry(
            input_ordinal=ordinal,
            phase=phase,
            budget_category=category,
            evidence=evidence,
            terminal_classification=f"prepared:{planned_terminal}",
            identical_retry=False,
            lifecycle=InputLifecycle.PREPARED,
            prior_progress_proven=prior_progress_proven,
            swipe_geometry=swipe,
        )
        self.state.journal.append(entry)
        self._persist_lifecycle(
            {
                "lifecycle": InputLifecycle.PREPARED.value,
                "input_ordinal": ordinal,
                "phase": phase.value,
                "category": category.value,
                "swipe": list(swipe) if swipe else None,
                "prior_progress_proven": prior_progress_proven,
            }
        )
        return ordinal

    def mark_input_sent(self, ordinal: int, *, category: InputBudgetCategory) -> None:
        budget_error: str | None = None
        try:
            self.state.accounting = self.state.accounting.record(category)
        except ValueError as exc:
            budget_error = str(exc)
            self.state.unresolved = True
        self.state.transport_dispatched = True
        entry = self.state.journal[ordinal - 1]
        updated = NavigationJournalEntry(
            input_ordinal=entry.input_ordinal,
            phase=entry.phase,
            budget_category=entry.budget_category,
            evidence=entry.evidence,
            terminal_classification=(
                "input_sent" if budget_error is None else f"input_sent_budget_error:{budget_error}"
            ),
            identical_retry=False,
            lifecycle=InputLifecycle.INPUT_SENT,
            prior_progress_proven=entry.prior_progress_proven,
            swipe_geometry=entry.swipe_geometry,
        )
        self.state.journal[ordinal - 1] = updated
        if updated.swipe_geometry is not None:
            self.state.last_swipe = updated.swipe_geometry
        self._persist_lifecycle(
            {
                "lifecycle": InputLifecycle.INPUT_SENT.value,
                "input_ordinal": ordinal,
                "transport_inputs_used": self.state.accounting.transport_inputs_used,
                "budget_error": budget_error,
            }
        )
        if budget_error is not None:
            raise RuntimeError(f"survey budget exceeded after transport: {budget_error}")

    def mark_terminal(
        self,
        ordinal: int,
        *,
        evidence: NavigationEvidenceSequence,
        terminal: str,
        unresolved: bool = False,
        progress_proven: bool | None = None,
    ) -> None:
        entry = self.state.journal[ordinal - 1]
        lifecycle = InputLifecycle.UNRESOLVED if unresolved else InputLifecycle.TERMINAL
        if unresolved:
            self.state.unresolved = True
        if progress_proven is not None:
            self.state.last_progress_proven = progress_proven
        updated = NavigationJournalEntry(
            input_ordinal=entry.input_ordinal,
            phase=entry.phase,
            budget_category=entry.budget_category,
            evidence=evidence,
            terminal_classification=terminal,
            identical_retry=False,
            lifecycle=lifecycle,
            prior_progress_proven=entry.prior_progress_proven,
            swipe_geometry=entry.swipe_geometry,
        )
        self.state.journal[ordinal - 1] = updated
        _append_jsonl(self.journal_path, updated.to_dict())
        self._persist_lifecycle(
            {
                "lifecycle": lifecycle.value,
                "input_ordinal": ordinal,
                "terminal": terminal,
                "unresolved": unresolved,
                "transport_inputs_used": self.state.accounting.transport_inputs_used,
            }
        )

    def _close_dispatch_exception(
        self,
        *,
        ordinal: int,
        source_rel: str,
        before_rel: str,
        transport_rel: str,
        exc: BaseException,
        transport_gate: Mapping[str, bool],
        post_rel: str | None = None,
    ) -> None:
        """Close prepared dispatch: zero-transport fail-closed vs ambiguous/unresolved.

        ``before_rel`` / ``post_rel`` must be the fresh immediate-before and
        immediate-post captures when available — never the planning frame for both.
        """

        input_sent = bool(transport_gate.get("input_sent"))
        attempted = bool(transport_gate.get("attempted"))
        entry = self.state.journal[ordinal - 1]
        if entry.lifecycle is InputLifecycle.INPUT_SENT:
            input_sent = True
        immediate_post = post_rel if post_rel else before_rel
        evidence = NavigationEvidenceSequence(
            source_path=source_rel,
            immediate_before_path=before_rel,
            transport_record_path=transport_rel,
            immediate_post_path=immediate_post,
            semantic_result_path=transport_rel,
        )
        if input_sent or attempted:
            # Durable INPUT_SENT or ambiguous transport without recorded input_sent.
            if attempted and not input_sent:
                self.state.unresolved = True
                self.state.transport_dispatched = True
            self.mark_terminal(
                ordinal,
                evidence=evidence,
                terminal=f"unresolved_safe_action:{exc}",
                unresolved=True,
            )
            return
        # Zero-transport pre-dispatch block: close prepared without unresolved inflation.
        self.mark_terminal(
            ordinal,
            evidence=evidence,
            terminal=f"blocked_fail_closed_zero_transport:{exc}",
            unresolved=False,
        )

    def import_home_entry_accounting(
        self,
        *,
        entry: Mapping[str, Any],
        source_rel: str,
        before_rel: str,
        transport_rel: str,
        post_rel: str,
    ) -> int:
        """Import exact Home Atlas SafeActionExecutor transport counts; no re-dispatch."""

        exact = count_home_entry_transports(entry)
        for index in range(exact):
            if not _budget_has_capacity(self.state.accounting, InputBudgetCategory.AUXILIARY):
                raise RuntimeError("auxiliary budget exhausted importing Home entry transports")
            fragment = f"{transport_rel}#home_atlas_safe_action={index + 1}"
            ordinal = len(self.state.journal) + 1
            evidence = NavigationEvidenceSequence(
                source_path=source_rel,
                immediate_before_path=before_rel,
                transport_record_path=fragment,
                immediate_post_path=post_rel,
                semantic_result_path=fragment,
            )
            self.state.accounting = self.state.accounting.record(InputBudgetCategory.AUXILIARY)
            self.state.transport_dispatched = True
            journal_entry = NavigationJournalEntry(
                input_ordinal=ordinal,
                phase=SurveyPhase.SAFE_TERMINAL,
                budget_category=InputBudgetCategory.AUXILIARY,
                evidence=evidence,
                terminal_classification="imported_home_atlas_safe_action",
                identical_retry=False,
                lifecycle=InputLifecycle.TERMINAL,
                prior_progress_proven=False,
                swipe_geometry=None,
            )
            self.state.journal.append(journal_entry)
            _append_jsonl(self.journal_path, journal_entry.to_dict())
            self._persist_lifecycle(
                {
                    "lifecycle": InputLifecycle.TERMINAL.value,
                    "input_ordinal": ordinal,
                    "terminal": "imported_home_atlas_safe_action",
                    "imported_from": "run_verified_campaign_home_atlas_entry",
                    "transport_inputs_used": self.state.accounting.transport_inputs_used,
                }
            )
        return exact

    def _execute_via_safe_action(
        self,
        *,
        observation: Observation,
        action_key: str,
        semantic_action: str,
        transport_fn,
        recapture_fn,
        post_observe_fn,
        reconcile_fn,
    ):
        action_id = f"{FLOW_ID}:{action_key}:{uuid.uuid4().hex[:12]}"
        now = time.monotonic()
        # Capability binds to the fresh observation. Executor proposal is slightly
        # older so same-capture recapture rebuild remains IMMEDIATE_RECAPTURE fresh
        # (Home Atlas pan binding), without weakening digest equality.
        proposal_observation = replace(
            observation,
            capture_completed_monotonic=float(observation.capture_completed_monotonic) - 0.05,
        )
        issue_request = _build_survey_policy_request(
            observation=observation,
            action_id=action_id,
            action_key=action_key,
            lease_owner=self.lease_owner,
            navigation_session_id=self.session_id,
            monotonic_now=now,
            semantic_action=semantic_action,
        )
        issued = self.policy.issue_capability(issue_request)
        if not issued.authorized or issued.capability is None:
            raise RuntimeError(
                f"SafeActionExecutor capability denied for {action_key}: {issued.reason_code}"
            )
        executor = SafeActionExecutor(
            self.store,
            self.policy,
            self.lease_owner,
            time.monotonic,
            transport_fn,
            recapture_fn,
            post_observe_fn,
            reconcile_fn,
            wall_clock=time.time,
            max_pre_dispatch_attempts=1,
        )
        execute_request = _build_survey_policy_request(
            observation=proposal_observation,
            action_id=action_id,
            action_key=action_key,
            lease_owner=self.lease_owner,
            navigation_session_id=self.session_id,
            monotonic_now=time.monotonic(),
            semantic_action=semantic_action,
        )
        result = executor.execute(execute_request, issued.capability, dry_run=False)
        if result.transport_calls < 1:
            raise RuntimeError(f"SafeActionExecutor issued zero transport for {action_key}")
        if result.status is ActionStatus.UNRESOLVED:
            raise RuntimeError(f"SafeActionExecutor unresolved for {action_key}")
        return result

    def dispatch_swipe(
        self,
        *,
        phase: SurveyPhase,
        category: InputBudgetCategory,
        source_rel: str,
        before,
        before_prov: NativeFrameProvenance,
        before_rel: str,
        swipe: tuple[int, int, int, int, int],
        action_key: str,
        target_identity: str,
        prior_progress_proven: bool,
    ) -> tuple[Any, Any, str, Any]:
        # Planning ``before`` / ``before_rel`` only establish geometry/budget for the
        # caller. Capability issue and consume bind to one fresh immediate-before.
        del before, before_prov, before_rel  # planning frame is not the issuance capture
        fresh, fresh_prov = self.capture(f"{action_key}-immediate-before")
        if self.recognize(fresh.frame).observation.screen != CampaignScreen.TIER_MAP:
            raise RuntimeError("survey pan immediate-before is not TIER_MAP")
        fresh_rel = _rel(self.session, fresh.path)
        transport = self.session / f"{action_key}-transport.json"
        transport.write_text(
            json.dumps(
                {
                    "swipe": list(swipe),
                    "action_key": action_key,
                    "authority": "SafeActionExecutor",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        transport_rel = _rel(self.session, transport)
        ordinal = self.prepare_input(
            phase=phase,
            category=category,
            before_rel=fresh_rel,
            transport_rel=transport_rel,
            source_rel=source_rel,
            swipe=swipe,
            prior_progress_proven=prior_progress_proven,
            planned_terminal=target_identity,
        )
        drag_start = (swipe[0], swipe[1])
        drag_end = (swipe[2], swipe[3])
        observation = _build_survey_observation(
            frame_sha256=fresh.sha256,
            capture_completed_monotonic=fresh.captured_monotonic,
            target_identity=target_identity,
            target_roi=gesture_geometry_roi(drag_start, drag_end),
            semantic_action=SURVEY_PAN_SEMANTIC_ACTION,
            expected_postcondition=SURVEY_PAN_POSTCONDITION,
        )
        post_holder: dict[str, Any] = {}
        dispatch_holder: dict[str, Any] = {"frame": fresh, "provenance": fresh_prov}
        transport_gate: dict[str, bool] = {"attempted": False, "input_sent": False}

        def recapture_fn() -> Observation:
            # Rebuild a distinct Observation from the same fresh immediate-before
            # identity used for capability issuance. Do not recapture; HUD digest
            # drift on a second grab would CAPABILITY_CAPTURE_MISMATCH fail-close.
            rebuilt = _build_survey_observation(
                frame_sha256=fresh.sha256,
                capture_completed_monotonic=fresh.captured_monotonic,
                target_identity=target_identity,
                target_roi=gesture_geometry_roi(drag_start, drag_end),
                semantic_action=SURVEY_PAN_SEMANTIC_ACTION,
                expected_postcondition=SURVEY_PAN_POSTCONDITION,
            )
            if rebuilt is observation:
                raise RuntimeError("RECAPTURE_MUST_REBUILD_DISTINCT_OBSERVATION")
            return replace(
                rebuilt,
                evidence_refs=observation.evidence_refs + (fresh_rel,),
            )

        def transport_fn(_intent) -> TransportResult:
            transport_gate["attempted"] = True
            reject_direct_survey_transport(authorized_token=_SURVEY_TRANSPORT_SEAL)
            dispatch_frame = dispatch_holder["frame"]
            self.runtime.swipe(
                dispatch_frame,
                start=drag_start,
                end=drag_end,
                action_key=action_key,
                target_identity=target_identity,
            )
            self.mark_input_sent(ordinal, category=category)
            transport_gate["input_sent"] = True
            return TransportResult(True, "CAMPAIGN_ATLAS_PAN_DISPATCHED")

        def post_observe():
            time.sleep(0.7)
            post, post_prov = self.capture(f"{action_key}-post")
            # Retain fresh post paths before measurement so dispatch-exception
            # journaling can reference them when provenance/measurement fails.
            post_holder["post"] = post
            post_holder["post_prov"] = post_prov
            dispatch_frame = dispatch_holder["frame"]
            dispatch_prov = dispatch_holder["provenance"]
            measured = measure_campaign_frame_pair(
                post.frame,
                dispatch_frame.frame,
                candidate_provenance=post_prov,
                reference_provenance=dispatch_prov,
                backend=self.backend,
            )
            post_holder["measurement"] = measured
            post_holder["outcome"] = registration_progress_outcome(measured.measurement)
            return (
                replace(
                    observation,
                    frame_sha256=post.sha256,
                    capture_completed_monotonic=post.captured_monotonic,
                    target_identity=None,
                    target_roi=None,
                ),
            )

        def reconcile(_intent, _observation: Observation) -> bool:
            post = post_holder.get("post")
            return bool(
                post is not None
                and self.recognize(post.frame).observation.screen == CampaignScreen.TIER_MAP
                and post_holder.get("outcome") in {"progress", "no_progress"}
            )

        try:
            self._execute_via_safe_action(
                observation=observation,
                action_key=action_key,
                semantic_action=SURVEY_PAN_SEMANTIC_ACTION,
                transport_fn=transport_fn,
                recapture_fn=recapture_fn,
                post_observe_fn=post_observe,
                reconcile_fn=reconcile,
            )
        except Exception as exc:
            post = post_holder.get("post")
            post_rel = _rel(self.session, post.path) if post is not None else None
            self._close_dispatch_exception(
                ordinal=ordinal,
                source_rel=source_rel,
                before_rel=fresh_rel,
                transport_rel=transport_rel,
                exc=exc,
                transport_gate=transport_gate,
                post_rel=post_rel,
            )
            raise
        post = post_holder["post"]
        post_prov = post_holder["post_prov"]
        observation_meas = post_holder["measurement"]
        residual = registration_residual_report(observation_meas)
        self.state.residuals.append(residual)
        outcome = registration_progress_outcome(observation_meas.measurement)
        result_path = self.session / f"{action_key}-result.json"
        result_path.write_text(
            json.dumps(
                {**asdict(residual), "progress_outcome": outcome},
                indent=2,
                sort_keys=True,
                default=str,
            ),
            encoding="utf-8",
        )
        evidence = NavigationEvidenceSequence(
            source_path=source_rel,
            immediate_before_path=_rel(self.session, dispatch_holder["frame"].path),
            transport_record_path=transport_rel,
            immediate_post_path=_rel(self.session, post.path),
            semantic_result_path=_rel(self.session, result_path),
        )
        if outcome == "unresolved":
            self.mark_terminal(
                ordinal,
                evidence=evidence,
                terminal="registration_unresolved",
                unresolved=True,
                progress_proven=False,
            )
        elif outcome == "no_progress":
            self.mark_terminal(
                ordinal,
                evidence=evidence,
                terminal="clamp",
                unresolved=False,
                progress_proven=False,
            )
        else:
            self.mark_terminal(
                ordinal,
                evidence=evidence,
                terminal="progress",
                unresolved=False,
                progress_proven=True,
            )
        return post, post_prov, outcome, observation_meas.measurement

    def dispatch_bound_tap(
        self,
        *,
        phase: SurveyPhase,
        category: InputBudgetCategory,
        source_rel: str,
        before,
        before_rel: str,
        identity: str,
        action_key: str,
        expected_successor,
    ) -> tuple[Any, Any]:
        # Planning ``before`` / ``before_rel`` only scope the caller. Capability issue,
        # measured ROI, recapture rebuild, and tap dispatch bind to one fresh
        # immediate-before identity. Never reuse the planning frame digest and never
        # live-grab again after issue.
        del before, before_rel  # planning frame is not the issuance capture
        fresh, _fresh_prov = self.capture(f"{action_key}-immediate-before")
        fresh_recognition = self.recognize(fresh.frame)
        if fresh_recognition.observation.screen != CampaignScreen.TIER_MAP:
            raise RuntimeError("survey tap immediate-before is not TIER_MAP")
        # Fail closed with zero transport when the target cannot be measured on
        # this one fresh frame (no planning-ROI fallback).
        roi = require_bound_survey_target(
            fresh_recognition, identity, frame=fresh.frame
        )
        fresh_rel = _rel(self.session, fresh.path)
        transport = self.session / f"{action_key}-transport.json"
        transport.write_text(
            json.dumps(
                {
                    "tap_identity": identity,
                    "roi": list(roi),
                    "authority": "SafeActionExecutor",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        transport_rel = _rel(self.session, transport)
        ordinal = self.prepare_input(
            phase=phase,
            category=category,
            before_rel=fresh_rel,
            transport_rel=transport_rel,
            source_rel=source_rel,
            swipe=None,
            prior_progress_proven=False,
            planned_terminal=identity,
        )
        observation = _build_survey_observation(
            frame_sha256=fresh.sha256,
            capture_completed_monotonic=fresh.captured_monotonic,
            target_identity=identity,
            target_roi=roi,
            semantic_action=SURVEY_TAP_SEMANTIC_ACTION,
            expected_postcondition=SURVEY_TAP_POSTCONDITION,
        )
        post_holder: dict[str, Any] = {}
        dispatch_holder: dict[str, Any] = {"frame": fresh, "roi": roi}
        transport_gate: dict[str, bool] = {"attempted": False, "input_sent": False}

        def recapture_fn() -> Observation:
            # Remeasure on the same fresh frame; ROI drift or unknown target fails
            # closed with zero transport. Rebuild a distinct Observation from the
            # issuance identity — do not capture again (HUD digest drift).
            remeasure_recognition = self.recognize(fresh.frame)
            if remeasure_recognition.observation.screen != CampaignScreen.TIER_MAP:
                raise RuntimeError("survey tap immediate-before is not TIER_MAP")
            rebound = require_bound_survey_target(
                remeasure_recognition, identity, frame=fresh.frame
            )
            verified_roi = require_stable_survey_tap_rebound(
                proposal_roi=observation.target_roi,
                rebound_roi=rebound,
            )
            dispatch_holder["roi"] = verified_roi
            rebuilt = _build_survey_observation(
                frame_sha256=fresh.sha256,
                capture_completed_monotonic=fresh.captured_monotonic,
                target_identity=identity,
                target_roi=observation.target_roi,
                semantic_action=SURVEY_TAP_SEMANTIC_ACTION,
                expected_postcondition=SURVEY_TAP_POSTCONDITION,
            )
            if rebuilt is observation:
                raise RuntimeError("RECAPTURE_MUST_REBUILD_DISTINCT_OBSERVATION")
            return replace(
                rebuilt,
                evidence_refs=observation.evidence_refs + (fresh_rel,),
            )

        def transport_fn(_intent) -> TransportResult:
            transport_gate["attempted"] = True
            reject_direct_survey_transport(authorized_token=_SURVEY_TRANSPORT_SEAL)
            dispatch_frame = dispatch_holder["frame"]
            dispatch_roi = dispatch_holder["roi"]
            if survey_target_is_consequential(identity):
                raise RuntimeError(f"consequential target prohibited for survey: {identity}")
            self.runtime.tap(
                dispatch_frame,
                target_identity=identity,
                target_roi=dispatch_roi,
                action_key=action_key,
                consequential=False,
            )
            self.mark_input_sent(ordinal, category=category)
            transport_gate["input_sent"] = True
            return TransportResult(True, "CAMPAIGN_ATLAS_TAP_DISPATCHED")

        def post_observe():
            time.sleep(0.8)
            post, post_prov = self.capture(f"{action_key}-post")
            post_holder["post"] = post
            post_holder["post_prov"] = post_prov
            return (
                replace(
                    observation,
                    frame_sha256=post.sha256,
                    capture_completed_monotonic=post.captured_monotonic,
                    target_identity=None,
                    target_roi=None,
                ),
            )

        def reconcile(_intent, _observation: Observation) -> bool:
            post = post_holder.get("post")
            return bool(post is not None and expected_successor(self.recognize(post.frame)))

        try:
            self._execute_via_safe_action(
                observation=observation,
                action_key=action_key,
                semantic_action=SURVEY_TAP_SEMANTIC_ACTION,
                transport_fn=transport_fn,
                recapture_fn=recapture_fn,
                post_observe_fn=post_observe,
                reconcile_fn=reconcile,
            )
        except Exception as exc:
            post = post_holder.get("post")
            post_rel = _rel(self.session, post.path) if post is not None else None
            self._close_dispatch_exception(
                ordinal=ordinal,
                source_rel=source_rel,
                before_rel=fresh_rel,
                transport_rel=transport_rel,
                exc=exc,
                transport_gate=transport_gate,
                post_rel=post_rel,
            )
            raise
        post = post_holder["post"]
        post_prov = post_holder["post_prov"]
        result_path = self.session / f"{action_key}-result.json"
        result_path.write_text(
            json.dumps(
                {
                    "screen": self.recognize(post.frame).observation.screen.value,
                    "identity": identity,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        ann = _annotate_roi(
            self.session,
            dispatch_holder["frame"].frame,
            label=identity,
            roi=dispatch_holder["roi"],
            digest=dispatch_holder["frame"].sha256,
        )
        self.state.annotation_paths.append(ann)
        evidence = NavigationEvidenceSequence(
            source_path=source_rel,
            immediate_before_path=_rel(self.session, dispatch_holder["frame"].path),
            transport_record_path=transport_rel,
            immediate_post_path=_rel(self.session, post.path),
            semantic_result_path=_rel(self.session, result_path),
        )
        self.mark_terminal(ordinal, evidence=evidence, terminal=identity, unresolved=False)
        return post, post_prov


def _preflight_blocked_delivery(
    *,
    session: Path,
    serial: str,
    runtime_owner: str,
    prior_accounting: InputBudgetAccounting | None = None,
    prior_continuation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    blockers = list(live_survey_preflight_blockers())
    reason = "; ".join(blockers)
    accounting = prior_accounting if prior_accounting is not None else InputBudgetAccounting()
    continuation = dict(prior_continuation or {})
    prior_seeded = int(continuation.get("prior_inputs_seeded") or 0)
    used = int(accounting.transport_inputs_used)
    if prior_seeded and prior_seeded != used:
        raise RuntimeError(
            "preflight blocked delivery prior seed must match seeded InputBudgetAccounting"
        )
    # Session report journal is empty (no current-session inputs). Cumulative used lives on
    # durable accounting + delivery result, not fabricated journal rows.
    empty = SurveySessionReport(
        manifest=SurveySessionManifest(
            schema_version=1,
            flow_id=FLOW_ID,
            session_id=f"campaign-atlas-survey-{session.name}",
            contract_kind=ContractKind.ACTIVATED,
            profile_id=CAMPAIGN_PROFILE_ID,
            platform=CAMPAIGN_PLATFORM,
            package=CAMPAIGN_PACKAGE,
            mask_contract_id=MASK_CONTRACT_ID,
            native_width=800,
            native_height=1280,
            maximum_transport_inputs=ACTIVATED_TRANSPORT_INPUT_CEILING,
            maximum_sessions=1,
            session_index=1,
            created_at_utc=_utc_now(),
        ),
        accounting=InputBudgetAccounting(),
        accepted_frames=(),
        rejected_frames=(),
        journal=(),
        edge_clamps=(),
        overlaps=(),
        registration_residuals=(),
        coverage_gaps=(
            CoverageGapReport(
                gap_id="live_preflight",
                description=reason,
                unresolved=True,
            ),
        ),
        loop_closure=None,
        cross_difficulty=None,
        landmarks=(),
        safe_terminal=None,
        disposition=CollectorDisposition.EVIDENCE_REQUIRED,
        reason=reason,
        transport_dispatched=False,
    )
    validate_survey_session_report(empty)
    report_path = session / "survey-session-report.json"
    report_path.write_text(
        json.dumps(empty.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    classification = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "accepted_frames": [],
        "rejected_frames": [],
        "accepted_count": 0,
        "rejected_count": 0,
        "notes": "pre-input evidence_required; no retained live frames",
    }
    (session / FRAME_CLASSIFICATION_PATH).write_text(
        json.dumps(classification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name in (
        "events.jsonl",
        "ledger.jsonl",
        "capability-audit.jsonl",
        "journal.jsonl",
        LIFECYCLE_PATH,
    ):
        path = session / name
        if not path.exists():
            path.write_text("", encoding="utf-8")
    write_survey_continuation_reference(session, continuation)
    (session / ACCOUNTING_PATH).write_text(
        json.dumps(
            {
                "transport_inputs_used": used,
                "accounting": accounting.to_dict(),
                "unresolved": False,
                "transport_dispatched": False,
                "open_prepared": False,
                "journal_len": 0,
                "input_sent_count": 0,
                "session_navigation_inputs_sent": 0,
                "prior_inputs_seeded": prior_seeded,
                "updated_at_utc": _utc_now(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "blocked",
        "serial": serial,
        "native_width": 800,
        "native_height": 1280,
        "runtime_owner": runtime_owner,
        "terminal_runtime_state": "safe_blocked_terminal",
        "survey_result": {
            "terminal": "evidence_required",
            "reason": reason,
            "transport_dispatched": False,
            "navigation_inputs_used": used,
            "session_navigation_inputs_sent": 0,
            "maximum_navigation_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
            "session_report_path": "survey-session-report.json",
            "frame_classification_path": FRAME_CLASSIFICATION_PATH,
            "live_preflight_inadmissible": True,
            "preflight_blockers": blockers,
            "unresolved": False,
            "prior_continuation": continuation,
            "call_graph": production_survey_call_graph(),
        },
        "actions": [
            {
                "action_class": "navigation_only",
                "outcome": "evidence_required",
                "transport_dispatched": False,
                "navigation_inputs_used": used,
            }
        ],
        "events_path": "events.jsonl",
        "ledger_path": "ledger.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "journal_path": "journal.jsonl",
        "frames": [],
        "operator_returncode": 0,
    }
    (session / "flow-delivery-result.json").write_text(
        json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return delivery


def run_bounded_campaign_atlas_survey(
    *,
    session: Path,
    adb: str,
    serial: str,
    runtime_owner: str,
    prior_accounting: InputBudgetAccounting | None = None,
    prior_continuation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    require_campaign_home_atlas_building(DEFAULT_HOME_ATLAS)
    # Finding 4/5: without measured non-static selectors and overlap association
    # policy, live traversal cannot meet task value. Stop pre-input.
    if not live_survey_preflight_is_admissible():
        return _preflight_blocked_delivery(
            session=session,
            serial=serial,
            runtime_owner=runtime_owner,
            prior_accounting=prior_accounting,
            prior_continuation=prior_continuation,
        )

    runner = ADBRunner(adb, serial)
    runtime = LocalBlueStacksRuntime(runner, session / "runtime", execute=True)
    session_id = f"campaign-atlas-survey-{session.name}"
    op = _SurveyOperator(
        session,
        runtime,
        session_id,
        lease_owner=runtime_owner,
        prior_accounting=prior_accounting,
        prior_continuation=prior_continuation,
    )
    try:
        return _run_live_survey_when_admissible(
            op=op,
            session=session,
            session_id=session_id,
            source_runtime=runtime,
            serial=serial,
            runtime_owner=runtime_owner,
        )
    finally:
        op.close()


def _run_live_survey_when_admissible(
    *,
    op: _SurveyOperator,
    session: Path,
    session_id: str,
    source_runtime: LocalBlueStacksRuntime,
    serial: str,
    runtime_owner: str,
) -> dict[str, Any]:
    """Live traversal path. Unreachable while LIVE_SURVEY_PREFLIGHT_BLOCKERS nonempty."""

    del source_runtime
    source, _source_prov = op.capture("source")
    source_rel = _rel(session, source.path)
    recognition = op.recognize(source.frame)
    _append_jsonl(
        op.events_path,
        {"type": "survey_source", "screen": recognition.observation.screen.value},
    )

    if recognition.observation.screen != CampaignScreen.TIER_MAP:
        # Reconciled EDGE / traversal progress seeds the post-progress viewport.
        # Re-entering from Home would discard that coverage and risk re-dispatch.
        prior_category = str(op.state.prior_continuation.get("prior_category") or "")
        if (
            prior_category
            in {
                KNOWN_CONTINUATION_MIXED_CATEGORY,
                KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY,
            }
            or int(op.state.prior_continuation.get("prior_edge_clamp_seeded") or 0) > 0
            or int(op.state.prior_continuation.get("prior_overlap_seeded") or 0) > 0
        ):
            raise RuntimeError(
                "evidence-backed map continuation requires source CAMPAIGN_TIER_MAP; "
                "refuse Home/VIP re-entry that would discard viewport progress"
            )
        before, _ = op.capture("entry-immediate-before")
        before_screen = op.recognize(before.frame).observation.screen
        if before_screen != CampaignScreen.HOME_BASE:
            # Bounded VIP Close recovery before unsupported-start failure.
            vip_gate = recognize_reset_popup(before.frame)
            if not vip_gate.get("recognized"):
                raise RuntimeError(
                    f"unsupported survey start screen: {before_screen.value}"
                )
            vip_dismiss = dismiss_campaign_vip_reset_popup(op, source_rel=source_rel)
            vip_path = session / "vip-reset-dismiss.json"
            vip_path.write_text(
                json.dumps(vip_dismiss, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
            _append_jsonl(
                op.events_path,
                {
                    "type": "vip_reset_dismiss",
                    "status": vip_dismiss.get("status"),
                    "reason": vip_dismiss.get("reason"),
                    "path": _rel(session, vip_path),
                },
            )
            if vip_dismiss.get("status") != "dismissed":
                if vip_dismiss.get("transport_dispatched"):
                    raise RuntimeError(
                        "VIP reset dismiss unresolved after transport: "
                        f"{vip_dismiss.get('reason')}"
                    )
                raise RuntimeError(
                    f"unsupported survey start screen: {before_screen.value} "
                    f"(vip_dismiss={vip_dismiss.get('reason')})"
                )
            # Confirmed dismissal: continue survey on Campaign TIER_MAP in this invocation.
            current, current_prov = op.capture("vip-reset-post-continue")
            if op.recognize(current.frame).observation.screen != CampaignScreen.TIER_MAP:
                raise RuntimeError(
                    "Campaign TIER_MAP not recognized after VIP reset dismiss continuation"
                )
        else:
            zoom_recovery = recover_home_zoom_before_campaign_entry(
                op,
                source_rel=source_rel,
                atlas_path=DEFAULT_HOME_ATLAS,
                maximum_zoom_inputs=4,
                settle_seconds=1.0,
            )
            zoom_path = session / "home-zoom-recovery.json"
            zoom_path.write_text(
                json.dumps(zoom_recovery, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
            _append_jsonl(
                op.events_path,
                {
                    "type": "home_zoom_recovery",
                    "status": zoom_recovery.get("status"),
                    "zoom_inputs": zoom_recovery.get("zoom_inputs"),
                    "path": _rel(session, zoom_path),
                },
            )
            if zoom_recovery.get("status") != "localized":
                raise RuntimeError(
                    f"Home zoom recovery failed before Campaign entry: {zoom_recovery.get('reason')}"
                )
            # Pre-zoom entry-immediate-before is stale after AUXILIARY zoom recovery.
            # Recapture post-localization before entry and import accounting.
            before, _ = op.capture("entry-immediate-before")
            if op.recognize(before.frame).observation.screen != CampaignScreen.HOME_BASE:
                raise RuntimeError(
                    "post-zoom entry immediate-before left HOME_BASE: "
                    f"{op.recognize(before.frame).observation.screen.value}"
                )
            entry = run_verified_campaign_home_atlas_entry(
                op.runtime,
                atlas_path=DEFAULT_HOME_ATLAS,
                maximum_pans=4,
                execute=True,
                settle_seconds=1.0,
                semantic_opened_check=lambda frame: op.recognize(frame).observation.screen
                == CampaignScreen.TIER_MAP,
            )
            transport = session / "entry-transport.json"
            transport.write_text(
                json.dumps(entry, indent=2, sort_keys=True, default=str), encoding="utf-8"
            )
            if entry.get("status") != "opened":
                raise RuntimeError(f"Home-to-Campaign entry failed: {entry.get('reason')}")
            post, _ = op.capture("entry-immediate-post")
            if op.recognize(post.frame).observation.screen != CampaignScreen.TIER_MAP:
                raise RuntimeError("Campaign TIER_MAP not recognized after Home-to-Campaign entry")
            op.import_home_entry_accounting(
                entry=entry,
                source_rel=source_rel,
                before_rel=_rel(session, before.path),
                transport_rel=_rel(session, transport),
                post_rel=_rel(session, post.path),
            )
            current = post
    else:
        current = source

    first_map_sha = current.sha256
    first_map_path = current.path
    edge_clamp_refs: dict[str, tuple[Any, NativeFrameProvenance]] = {}
    exit_resume = resolve_campaign_exit_only_resume(
        op.state.prior_continuation,
        current_screen=op.recognize(current.frame).observation.screen,
    )
    tier2_resume = resolve_difficulty_tier2_coverage_resume(
        op.state.prior_continuation,
        current_screen=op.recognize(current.frame).observation.screen,
    )
    edge_resume = resolve_reconciled_edge_coverage_resume(
        op.state.prior_continuation,
        current_screen=op.recognize(current.frame).observation.screen,
    )
    if (
        int(exit_resume["required"])
        + int(tier2_resume["required"])
        + int(edge_resume["required"])
        > 1
    ):
        raise RuntimeError("only one survey continuation resume mode may be required")
    if exit_resume["required"]:
        _append_jsonl(
            op.events_path,
            {
                "type": "campaign_exit_only_coverage_resume",
                "resume_action_key": exit_resume["resume_action_key"],
                "skip_prior_action_key_count": len(exit_resume["skip_prior_action_keys"]),
                "retained_tier2_post_frame": exit_resume["retained_tier2_post_frame"],
                "retained_tier2_post_sha256": exit_resume["retained_tier2_post_sha256"],
                "screen": CampaignScreen.TIER_MAP.value,
            },
        )
        # Fail closed unless fresh TIER_MAP still shows difficulty tier2 selected.
        require_tier_map_selection_state(current.frame, selected_tier=2)
        prior_tier2_session = Path(str(exit_resume["prior_session_directory"]))
        retained_rel = str(exit_resume["retained_tier2_post_frame"])
        retained_path = prior_tier2_session / retained_rel
        _retained_frame, _transport_digest, semantic, _width, _height = _native_frame_hashes(
            retained_path
        )
        if semantic != str(exit_resume["retained_tier2_post_sha256"]):
            raise RuntimeError("retained tier2 post frame hash mismatch")
        traversal_session = (
            prior_tier2_session.parent
            / str(exit_resume["retained_traversal_session_id"])
        )
        _hydrate_retained_survey_completion_evidence(
            op,
            traversal_session=traversal_session,
            tier2_session=prior_tier2_session,
        )
        if "campaign-exit-home" in set(exit_resume["skip_prior_action_keys"]):
            raise RuntimeError("refusing reissue of skipped campaign-exit-home")
        if op.recognize(current.frame).observation.screen != CampaignScreen.TIER_MAP:
            raise RuntimeError(
                "survey exit requires recognized Campaign TIER_MAP before home return"
            )
        before_exit, _ = op.capture("campaign-exit-home-before")
        require_tier_map_selection_state(before_exit.frame, selected_tier=2)
        home_frame, _home_prov = op.dispatch_bound_tap(
            phase=SurveyPhase.SAFE_TERMINAL,
            category=InputBudgetCategory.AUXILIARY,
            source_rel=source_rel,
            before=before_exit,
            before_rel=_rel(session, before_exit.path),
            identity="campaign-exit-base",
            action_key="campaign-exit-home",
            expected_successor=lambda rec: rec.observation.screen == CampaignScreen.HOME_BASE,
        )
        if op.recognize(home_frame.frame).observation.screen != CampaignScreen.HOME_BASE:
            raise RuntimeError(
                "survey did not return to recognized Home after campaign-exit-base"
            )
        current = home_frame
        op.state.safe_terminal = SafeTerminalReport(
            recognized=True,
            terminal_state=CampaignScreen.HOME_BASE.value,
            supporting_frame_sha256=current.sha256,
        )
        return _finalize_survey_delivery(
            op=op,
            session=session,
            session_id=session_id,
            source_rel=source_rel,
            first_map_sha=first_map_sha,
            first_map_path=first_map_path,
            serial=serial,
            runtime_owner=runtime_owner,
        )

    if tier2_resume["required"]:
        _append_jsonl(
            op.events_path,
            {
                "type": "difficulty_tier2_coverage_resume",
                "resume_action_key": tier2_resume["resume_action_key"],
                "skip_prior_action_key_count": len(tier2_resume["skip_prior_action_keys"]),
                "retained_tier1_post_frame": tier2_resume["retained_tier1_post_frame"],
                "retained_tier1_post_sha256": tier2_resume["retained_tier1_post_sha256"],
                "screen": CampaignScreen.TIER_MAP.value,
            },
        )
        # Import retained tier1 post geometry/provenance; never reissue edge/overlap/tier1.
        prior_session = Path(str(tier2_resume["prior_session_directory"]))
        retained_rel = str(tier2_resume["retained_tier1_post_frame"])
        retained_path = prior_session / retained_rel
        retained_frame, transport_digest, semantic, width, height = _native_frame_hashes(
            retained_path
        )
        if semantic != str(tier2_resume["retained_tier1_post_sha256"]):
            raise RuntimeError("retained tier1 post frame hash mismatch")
        tier_one_prov = NativeFrameProvenance(
            source_id=str(retained_path.as_posix()),
            capture_kind="fixture",
            runtime_session_id=prior_session.name,
            capture_ordinal=1,
            capture_completed_monotonic=0.0,
            transport_sha256=transport_digest,
            semantic_sha256=semantic,
            captured_at_utc=_utc_now(),
            width=width,
            height=height,
            profile_id=CAMPAIGN_PROFILE_ID,
            platform=CAMPAIGN_PLATFORM,
            package=CAMPAIGN_PACKAGE,
        )
        # Minimal frame holder compatible with measure_campaign_frame_pair callers.
        tier_one = type(
            "RetainedFrame",
            (),
            {"frame": retained_frame, "sha256": semantic, "path": retained_path},
        )()
        before_two, _ = op.capture("difficulty-tier-2-before")
        # Fail closed before transport unless fresh TIER_MAP has tier1 selected.
        require_tier_map_selection_state(before_two.frame, selected_tier=1)
        tier_two, tier_two_prov = op.dispatch_bound_tap(
            phase=SurveyPhase.DIFFICULTY_GEOMETRY_PAIR,
            category=InputBudgetCategory.AUXILIARY,
            source_rel=source_rel,
            before=before_two,
            before_rel=_rel(session, before_two.path),
            identity="campaign-tier-2",
            action_key="difficulty-tier-2",
            expected_successor=lambda rec: (
                rec.observation.screen == CampaignScreen.TIER_MAP
                and rec.observation.selected_tier == 2
            ),
        )
        if "difficulty-tier-2" in set(tier2_resume["skip_prior_action_keys"]):
            raise RuntimeError("refusing reissue of skipped difficulty-tier-2")
        difficulty_observation = measure_campaign_frame_pair(
            tier_two.frame,
            tier_one.frame,
            candidate_provenance=tier_two_prov,
            reference_provenance=tier_one_prov,
            backend=op.backend,
        )
        op.state.residuals.append(registration_residual_report(difficulty_observation))
        shared_geometry = overlap_association_accepted(difficulty_observation.measurement)
        op.state.cross_difficulty = CrossDifficultyGeometryReport(
            difficulty_a=1,
            difficulty_b=2,
            compared=True,
            used_as_recenter=False,
            conclusion=(
                "shared_world_layout_and_coordinate_geometry"
                if shared_geometry
                else "different_or_unresolved_world_geometry"
            ),
        )
        current = tier_two
        bind_landmarks_from_retained_frames(op, session)
        if not any(item.kind is LandmarkKind.CHAPTER for item in op.state.landmarks):
            raise RuntimeError("survey corpus lacks a spatially bound chapter landmark")
        if not any(
            item.kind in {LandmarkKind.PRISON_TRIAL, LandmarkKind.ULTIMATE_CHALLENGE}
            for item in op.state.landmarks
        ):
            raise RuntimeError("survey corpus lacks Prison Trial/Ultimate Challenge binding")
        if op.recognize(current.frame).observation.screen != CampaignScreen.TIER_MAP:
            raise RuntimeError(
                "survey exit requires recognized Campaign TIER_MAP before home return"
            )
        before_exit, _ = op.capture("campaign-exit-home-before")
        home_frame, _home_prov = op.dispatch_bound_tap(
            phase=SurveyPhase.SAFE_TERMINAL,
            category=InputBudgetCategory.AUXILIARY,
            source_rel=source_rel,
            before=before_exit,
            before_rel=_rel(session, before_exit.path),
            identity="campaign-exit-base",
            action_key="campaign-exit-home",
            expected_successor=lambda rec: rec.observation.screen == CampaignScreen.HOME_BASE,
        )
        if op.recognize(home_frame.frame).observation.screen != CampaignScreen.HOME_BASE:
            raise RuntimeError(
                "survey did not return to recognized Home after campaign-exit-base"
            )
        current = home_frame
        op.state.safe_terminal = SafeTerminalReport(
            recognized=True,
            terminal_state=CampaignScreen.HOME_BASE.value,
            supporting_frame_sha256=current.sha256,
        )
        return _finalize_survey_delivery(
            op=op,
            session=session,
            session_id=session_id,
            source_rel=source_rel,
            first_map_sha=first_map_sha,
            first_map_path=first_map_path,
            serial=serial,
            runtime_owner=runtime_owner,
        )

    if edge_resume["required"]:
        op.state.last_swipe = edge_resume["prior_progress_swipe"]
        op.state.last_progress_proven = True
        _append_jsonl(
            op.events_path,
            {
                "type": "edge_coverage_resume",
                "reconciled_action_key": edge_resume["reconciled_action_key"],
                "next_action_key": edge_resume["next_action_key"],
                "direction": edge_resume["direction"],
                "edge_start_step_by_direction": edge_resume["edge_start_step_by_direction"],
                "screen": CampaignScreen.TIER_MAP.value,
            },
        )

    for direction in _DIRECTIONS:
        gesture = hud_safe_pan_gesture(direction)
        swipe = gesture.as_swipe()
        clamped = False
        start_step = int(edge_resume["edge_start_step_by_direction"].get(direction, 0))
        if start_step < 0 or start_step > ACTIVATED_EDGE_STEPS_PER_DIRECTION:
            raise RuntimeError(f"edge resume start step out of range for {direction}")
        for step in range(start_step, ACTIVATED_EDGE_STEPS_PER_DIRECTION):
            action_key = f"edge-{direction}-{step:02d}"
            if (
                edge_resume["required"]
                and action_key == edge_resume["reconciled_action_key"]
            ):
                raise RuntimeError(
                    f"refuse re-dispatch of reconciled edge action_key={action_key}"
                )
            before, before_prov = op.capture(f"edge-{direction}-before-{step:02d}")
            if op.recognize(before.frame).observation.screen != CampaignScreen.TIER_MAP:
                raise RuntimeError(f"left TIER_MAP during {direction} edge survey")
            prior = op.state.last_progress_proven if op.state.last_swipe == swipe else False
            post, post_prov, outcome, _measurement = op.dispatch_swipe(
                phase=_PHASE_FOR_DIRECTION[direction],
                category=InputBudgetCategory.EDGE_CLAMP,
                source_rel=source_rel,
                before=before,
                before_prov=before_prov,
                before_rel=_rel(session, before.path),
                swipe=swipe,
                action_key=action_key,
                target_identity=f"campaign-atlas-edge-{direction}",
                prior_progress_proven=prior,
            )
            if outcome == "unresolved":
                raise RuntimeError(
                    f"edge {direction} registration unresolved; refusing progress claim"
                )
            if outcome == "no_progress":
                op.state.edge_clamps.append(
                    EdgeClampReport(
                        direction=direction,
                        clamp_observed=True,
                        supporting_frame_sha256=post.sha256,
                        notes=f"measured_no_progress_after_{step + 1}_steps",
                    )
                )
                edge_clamp_refs[direction] = (post, post_prov)
                ann = _annotate_roi(
                    session,
                    post.frame,
                    label=f"edge-clamp-{direction}",
                    roi=measured_content_annotation_roi(),
                    digest=post.sha256,
                )
                op.state.annotation_paths.append(ann)
                clamped = True
                current = post
                break
            current = post
        if not clamped:
            raise RuntimeError(
                f"edge clamp not observed for {direction} within "
                f"{ACTIVATED_EDGE_STEPS_PER_DIRECTION} steps"
            )

    overlap_steps = 0

    def overlap_pan(direction: str, label: str):
        nonlocal overlap_steps, current
        if overlap_steps >= ACTIVATED_OVERLAP_STEPS:
            raise RuntimeError("overlap traversal exhausted its 128-input ceiling")
        gesture = hud_safe_pan_gesture(direction)
        swipe = gesture.as_swipe()
        before, before_prov = op.capture(f"{label}-before")
        if op.recognize(before.frame).observation.screen != CampaignScreen.TIER_MAP:
            raise RuntimeError("overlap immediate-before is not TIER_MAP")
        prior = op.state.last_progress_proven if op.state.last_swipe == swipe else False
        post, post_prov, outcome, measurement = op.dispatch_swipe(
            phase=SurveyPhase.OVERLAPPING_VIEWPORTS,
            category=InputBudgetCategory.OVERLAP,
            source_rel=source_rel,
            before=before,
            before_prov=before_prov,
            before_rel=_rel(session, before.path),
            swipe=swipe,
            action_key=label,
            target_identity=f"campaign-atlas-overlap-{direction}",
            prior_progress_proven=prior,
        )
        overlap_steps += 1
        if outcome == "unresolved":
            raise RuntimeError(
                f"overlap association unresolved at {label}; refusing coverage claim"
            )
        if outcome == "progress":
            associated = overlap_association_accepted(measurement)
            op.state.overlaps.append(
                OverlapAssociationReport(
                    reference_sha256=before.sha256,
                    candidate_sha256=post.sha256,
                    overlap_ratio=float(measurement.overlap_ratio),
                    associated=associated,
                    notes=f"direction={direction};outcome={outcome}",
                )
            )
            if not associated:
                raise RuntimeError(
                    f"overlap association unresolved at {label}; refusing coverage claim"
                )
        # no_progress clamp steps are boundary evidence only — not overlap pairs.
        ann = _annotate_roi(
            session,
            post.frame,
            label=f"overlap-{direction}-{overlap_steps:03d}",
            roi=measured_content_annotation_roi(measurement),
            digest=post.sha256,
        )
        op.state.annotation_paths.append(ann)
        current = post
        return outcome, post, post_prov, measurement

    horizontal = "right"
    reached_top = False
    while overlap_steps < ACTIVATED_OVERLAP_STEPS:
        while overlap_steps < ACTIVATED_OVERLAP_STEPS:
            outcome, _, _, _ = overlap_pan(
                horizontal, f"overlap-row-{overlap_steps:03d}-{horizontal}"
            )
            if outcome == "no_progress":
                break
        if overlap_steps >= ACTIVATED_OVERLAP_STEPS:
            break
        outcome, _, _, _ = overlap_pan("top", f"overlap-row-step-{overlap_steps:03d}")
        if outcome == "no_progress":
            reached_top = True
            break
        horizontal = "left" if horizontal == "right" else "right"
    if not reached_top:
        raise RuntimeError("overlap traversal did not close vertical coverage before budget")

    top_right: tuple[Any, NativeFrameProvenance] | None = None
    while overlap_steps < ACTIVATED_OVERLAP_STEPS:
        outcome, post, post_prov, _ = overlap_pan(
            "right", f"overlap-loop-close-{overlap_steps:03d}"
        )
        if outcome == "no_progress":
            top_right = (post, post_prov)
            break
    if top_right is None or "right" not in edge_clamp_refs:
        raise RuntimeError("top-right loop-closure viewport was not retained")
    loop_frame, loop_prov = top_right
    reference_frame, reference_prov = edge_clamp_refs["right"]
    loop_observation = measure_campaign_frame_pair(
        loop_frame.frame,
        reference_frame.frame,
        candidate_provenance=loop_prov,
        reference_provenance=reference_prov,
        backend=op.backend,
    )
    op.state.residuals.append(registration_residual_report(loop_observation))
    if not loop_closure_accepted(loop_observation.measurement):
        raise RuntimeError("top-right loop closure failed reviewed registration policy")
    op.state.loop_closure = LoopClosureReport(
        closed=True,
        residual_px=float(loop_observation.measurement.residual_px),
        supporting_frame_sha256=loop_frame.sha256,
    )

    before_one, _ = op.capture("difficulty-tier-1-before")
    tier_one, tier_one_prov = op.dispatch_bound_tap(
        phase=SurveyPhase.DIFFICULTY_GEOMETRY_PAIR,
        category=InputBudgetCategory.AUXILIARY,
        source_rel=source_rel,
        before=before_one,
        before_rel=_rel(session, before_one.path),
        identity="campaign-tier-1",
        action_key="difficulty-tier-1",
        expected_successor=lambda rec: (
            rec.observation.screen == CampaignScreen.TIER_MAP
            and rec.observation.selected_tier == 1
        ),
    )
    before_two, _ = op.capture("difficulty-tier-2-before")
    tier_two, tier_two_prov = op.dispatch_bound_tap(
        phase=SurveyPhase.DIFFICULTY_GEOMETRY_PAIR,
        category=InputBudgetCategory.AUXILIARY,
        source_rel=source_rel,
        before=before_two,
        before_rel=_rel(session, before_two.path),
        identity="campaign-tier-2",
        action_key="difficulty-tier-2",
        expected_successor=lambda rec: (
            rec.observation.screen == CampaignScreen.TIER_MAP
            and rec.observation.selected_tier == 2
        ),
    )
    difficulty_observation = measure_campaign_frame_pair(
        tier_two.frame,
        tier_one.frame,
        candidate_provenance=tier_two_prov,
        reference_provenance=tier_one_prov,
        backend=op.backend,
    )
    op.state.residuals.append(registration_residual_report(difficulty_observation))
    shared_geometry = overlap_association_accepted(difficulty_observation.measurement)
    op.state.cross_difficulty = CrossDifficultyGeometryReport(
        difficulty_a=1,
        difficulty_b=2,
        compared=True,
        used_as_recenter=False,
        conclusion=(
            "shared_world_layout_and_coordinate_geometry"
            if shared_geometry
            else "different_or_unresolved_world_geometry"
        ),
    )
    current = tier_two

    bind_landmarks_from_retained_frames(op, session)
    if not any(item.kind is LandmarkKind.CHAPTER for item in op.state.landmarks):
        raise RuntimeError("survey corpus lacks a spatially bound chapter landmark")
    if not any(
        item.kind in {LandmarkKind.PRISON_TRIAL, LandmarkKind.ULTIMATE_CHALLENGE}
        for item in op.state.landmarks
    ):
        raise RuntimeError("survey corpus lacks Prison Trial/Ultimate Challenge binding")
    if op.recognize(current.frame).observation.screen != CampaignScreen.TIER_MAP:
        raise RuntimeError("survey exit requires recognized Campaign TIER_MAP before home return")
    before_exit, _ = op.capture("campaign-exit-home-before")
    home_frame, _home_prov = op.dispatch_bound_tap(
        phase=SurveyPhase.SAFE_TERMINAL,
        category=InputBudgetCategory.AUXILIARY,
        source_rel=source_rel,
        before=before_exit,
        before_rel=_rel(session, before_exit.path),
        identity="campaign-exit-base",
        action_key="campaign-exit-home",
        expected_successor=lambda rec: rec.observation.screen == CampaignScreen.HOME_BASE,
    )
    if op.recognize(home_frame.frame).observation.screen != CampaignScreen.HOME_BASE:
        raise RuntimeError("survey did not return to recognized Home after campaign-exit-base")
    current = home_frame
    op.state.safe_terminal = SafeTerminalReport(
        recognized=True,
        terminal_state=CampaignScreen.HOME_BASE.value,
        supporting_frame_sha256=current.sha256,
    )
    return _finalize_survey_delivery(
        op=op,
        session=session,
        session_id=session_id,
        source_rel=source_rel,
        first_map_sha=first_map_sha,
        first_map_path=first_map_path,
        serial=serial,
        runtime_owner=runtime_owner,
    )


def _finalize_survey_delivery(
    *,
    op: _SurveyOperator,
    session: Path,
    session_id: str,
    source_rel: str,
    first_map_sha: str,
    first_map_path: Path,
    serial: str,
    runtime_owner: str,
) -> dict[str, Any]:
    """Shared terminal packaging for a completed live survey (policy-gated)."""

    del source_rel, first_map_sha, first_map_path  # retained for future live path
    classification_path = _write_frame_classification_artifact(session, op.state)
    disposition = CollectorDisposition.NATIVE_SURVEY_COMPLETE
    reason = (
        "bounded native survey completed with four edge clamps, policy-accepted overlaps, "
        "loop closure, cross-difficulty comparison, landmark bindings, and recognized Home"
    )
    # Session report accounting is journal-scoped. Cumulative used stays on delivery.
    session_report_accounting = _session_scoped_report_accounting(op.state)
    report = SurveySessionReport(
        manifest=SurveySessionManifest(
            schema_version=1,
            flow_id=FLOW_ID,
            session_id=session_id,
            contract_kind=ContractKind.ACTIVATED,
            profile_id=CAMPAIGN_PROFILE_ID,
            platform=CAMPAIGN_PLATFORM,
            package=CAMPAIGN_PACKAGE,
            mask_contract_id=MASK_CONTRACT_ID,
            native_width=800,
            native_height=1280,
            maximum_transport_inputs=ACTIVATED_TRANSPORT_INPUT_CEILING,
            maximum_sessions=1,
            session_index=1,
            created_at_utc=_utc_now(),
        ),
        accounting=session_report_accounting,
        accepted_frames=tuple(op.state.accepted),
        rejected_frames=tuple(op.state.rejected),
        journal=tuple(op.state.journal),
        edge_clamps=tuple(op.state.edge_clamps),
        overlaps=tuple(op.state.overlaps),
        registration_residuals=tuple(op.state.residuals),
        coverage_gaps=tuple(op.state.coverage_gaps),
        loop_closure=op.state.loop_closure,
        cross_difficulty=op.state.cross_difficulty,
        landmarks=tuple(op.state.landmarks),
        safe_terminal=op.state.safe_terminal,
        disposition=disposition,
        reason=reason,
        transport_dispatched=op.state.transport_dispatched,
    )
    validate_survey_session_report(report)
    report_path = session / "survey-session-report.json"
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    runtime_frames = sorted((session / "runtime" / "frames").glob("*.png"))
    frame_names = [
        str(path.relative_to(session)).replace("\\", "/") for path in runtime_frames
    ]
    delivery = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "completed",
        "serial": serial,
        "native_width": 800,
        "native_height": 1280,
        "runtime_owner": runtime_owner,
        "terminal_runtime_state": "recognized_home",
        "survey_result": {
            "terminal": "native_survey_complete",
            "reason": reason,
            "transport_dispatched": True,
            "navigation_inputs_used": op.state.cumulative_navigation_inputs_used,
            "session_navigation_inputs_sent": op.state.session_navigation_inputs_sent,
            "maximum_navigation_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
            "session_report_path": "survey-session-report.json",
            "frame_classification_path": classification_path,
            "accounting": op.state.accounting.to_dict(),
            "prior_continuation": dict(op.state.prior_continuation),
            "unresolved": op.state.unresolved,
            "annotations": list(op.state.annotation_paths),
            "call_graph": production_survey_call_graph(),
            "safe_terminal": None
            if op.state.safe_terminal is None
            else asdict(op.state.safe_terminal),
        },
        "actions": [
            {
                "action_class": "navigation_only",
                "outcome": "native_survey_complete",
                "transport_dispatched": True,
                "navigation_inputs_used": op.state.cumulative_navigation_inputs_used,
            }
        ],
        "events_path": "events.jsonl",
        "ledger_path": "ledger.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "journal_path": "journal.jsonl",
        "frames": frame_names,
        "operator_returncode": 0,
    }
    (session / "flow-delivery-result.json").write_text(
        json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_accounting(session, op.state)
    return delivery


def bind_landmarks_from_retained_frames(op: _SurveyOperator, session: Path) -> None:
    for item in list(op.state.accepted):
        if item.provenance is None:
            continue
        path = Path(item.provenance.source_id)
        if not path.is_file():
            continue
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        recognition = op.recognize(frame)
        targets = dict(recognition.targets)
        hits = _ocr_hits(frame)
        for number in recognition.observation.visible_chapter_numbers:
            if any(
                landmark.kind is LandmarkKind.CHAPTER and landmark.label == f"Chapter {number}"
                for landmark in op.state.landmarks
            ):
                continue
            roi = chapter_roi_from_strong_spatial_evidence(
                number=number, targets=targets, hits=hits
            )
            if roi is None:
                continue
            ann = _annotate_roi(
                session,
                frame,
                label=f"campaign-chapter-{number}",
                roi=roi,
                digest=item.provenance.semantic_sha256,
            )
            op.state.annotation_paths.append(ann)
            op.state.landmarks.append(
                LandmarkBindingReport(
                    kind=LandmarkKind.CHAPTER,
                    label=f"Chapter {number}",
                    supporting_frame_sha256=item.provenance.semantic_sha256,
                    spatially_associated=True,
                    notes=f"annotation={ann}",
                )
            )
        prison_roi = prison_trial_roi_from_strong_spatial_evidence(hits)
        if prison_roi is not None and not any(
            landmark.kind is LandmarkKind.PRISON_TRIAL for landmark in op.state.landmarks
        ):
            ann = _annotate_roi(
                session,
                frame,
                label="prison-trial",
                roi=prison_roi,
                digest=item.provenance.semantic_sha256,
            )
            op.state.annotation_paths.append(ann)
            op.state.landmarks.append(
                LandmarkBindingReport(
                    kind=LandmarkKind.PRISON_TRIAL,
                    label="Prison Trial",
                    supporting_frame_sha256=item.provenance.semantic_sha256,
                    spatially_associated=True,
                    notes=f"annotation={ann}",
                )
            )
        uc = recognize_ultimate_challenge_entry_from_texts(
            campaign_screen_recognized=recognition.observation.screen
            == CampaignScreen.TIER_MAP,
            ocr_hits=hits,
            source_frame_sha256=item.provenance.semantic_sha256,
            reset_identity=None,
        )
        entry_roi = ultimate_challenge_entry_roi_from_ocr_hits(hits)
        if entry_observation_is_bound(uc) and entry_roi is not None:
            ann = _annotate_roi(
                session,
                frame,
                label="ultimate-challenge",
                roi=entry_roi,
                digest=item.provenance.semantic_sha256,
            )
            op.state.annotation_paths.append(ann)
            if not any(
                landmark.kind is LandmarkKind.ULTIMATE_CHALLENGE for landmark in op.state.landmarks
            ):
                op.state.landmarks.append(
                    LandmarkBindingReport(
                        kind=LandmarkKind.ULTIMATE_CHALLENGE,
                        label="Ultimate Challenge",
                        supporting_frame_sha256=item.provenance.semantic_sha256,
                        spatially_associated=True,
                        notes=f"annotation={ann}",
                    )
                )


def _failure_delivery_from_session(
    session: Path,
    *,
    serial: str,
    runtime_owner: str,
    exc: BaseException,
) -> dict[str, Any]:
    durable = load_durable_survey_accounting(session)
    used = int(durable.get("transport_inputs_used") or 0)
    open_prepared = bool(durable.get("open_prepared")) or survey_has_open_prepared_lifecycle(
        session
    )
    continuation_path = session / CONTINUATION_PATH
    prior_continuation: dict[str, Any] = {}
    if continuation_path.is_file():
        prior_continuation = json.loads(continuation_path.read_text(encoding="utf-8"))
    prior_seeded = int(
        durable.get("prior_inputs_seeded")
        if durable.get("prior_inputs_seeded") is not None
        else prior_continuation.get("prior_inputs_seeded")
        or 0
    )
    lifecycle_sent = _count_session_lifecycle_input_sent(session)
    if durable.get("input_sent_count") is not None:
        session_sent = max(int(durable.get("input_sent_count") or 0), lifecycle_sent)
    elif durable.get("session_navigation_inputs_sent") is not None:
        session_sent = max(
            int(durable.get("session_navigation_inputs_sent") or 0), lifecycle_sent
        )
    else:
        session_sent = max(0, lifecycle_sent, used - prior_seeded)
    # Current-session transport only; open-prepared remains ambiguous (may have transported).
    # Never treat cumulative/seeded used alone as this-session dispatch.
    transported = (
        bool(durable.get("transport_dispatched")) or session_sent > 0 or open_prepared
    )
    # unresolved_unsafe only for this session's durable unresolved / open prepared lifecycle.
    unresolved = bool(durable.get("unresolved")) or open_prepared
    frames: list[str] = []
    runtime_frames = session / "runtime" / "frames"
    if runtime_frames.is_dir():
        frames = [
            str(path.relative_to(session)).replace("\\", "/")
            for path in sorted(runtime_frames.glob("*.png"))
        ]
    if unresolved:
        terminal_runtime = "unresolved_unsafe"
        survey_terminal = "unresolved"
        status = "failed"
    else:
        terminal_runtime = "safe_blocked_terminal"
        survey_terminal = "blocked_fail_closed"
        status = "failed"
    for name in (
        "events.jsonl",
        "ledger.jsonl",
        "capability-audit.jsonl",
        "journal.jsonl",
        LIFECYCLE_PATH,
    ):
        path = session / name
        if not path.exists():
            path.write_text("", encoding="utf-8")
    return {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": status,
        "serial": serial,
        "native_width": 800,
        "native_height": 1280,
        "runtime_owner": runtime_owner,
        "terminal_runtime_state": terminal_runtime,
        "survey_result": {
            "terminal": survey_terminal,
            "reason": str(exc),
            "transport_dispatched": transported,
            "navigation_inputs_used": used,
            "session_navigation_inputs_sent": session_sent,
            "maximum_navigation_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
            "session_report_path": "survey-session-report.json",
            "unresolved": unresolved,
            "open_prepared": open_prepared,
            "durable_accounting": durable,
            "prior_continuation": prior_continuation,
        },
        "actions": [
            {
                "action_class": "navigation_only",
                "outcome": survey_terminal,
                "transport_dispatched": transported,
                "navigation_inputs_used": used,
            }
        ],
        "events_path": "events.jsonl",
        "ledger_path": "ledger.jsonl",
        "capability_audit_path": "capability-audit.jsonl",
        "journal_path": "journal.jsonl",
        "frames": frames,
        "operator_returncode": 1,
    }


def run_campaign_atlas_native_survey(
    queue: Mapping[str, Any], lease: Mapping[str, Any]
) -> str:
    pnsctl = _pnsctl()
    flow = next(item for item in queue["flows"] if item["flow_id"] == FLOW_ID)
    _require_survey_budget(flow)
    try:
        prior_accounting, prior_continuation = resolve_evidence_backed_prior_auxiliary_seed(
            artifact_root=pnsctl.BLUESTACKS_ARTIFACT_ROOT,
            claimed_navigation_inputs_used=int(flow.get("navigation_inputs_used") or 0),
        )
    except Exception as exc:
        raise pnsctl.OperatorError(
            f"Campaign atlas survey prior-accounting seed rejected: {exc}"
        ) from exc
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"survey-{stamp}"
    session.mkdir(parents=True, exist_ok=False)
    try:
        delivery = run_bounded_campaign_atlas_survey(
            session=session,
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            runtime_owner=str(lease["owner"]),
            prior_accounting=prior_accounting,
            prior_continuation=prior_continuation,
        )
    except Exception as exc:
        failure = _failure_delivery_from_session(
            session,
            serial=pnsctl.BLUESTACKS_SERIAL,
            runtime_owner=str(lease["owner"]),
            exc=exc,
        )
        (session / "flow-delivery-result.json").write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise pnsctl.OperatorError(f"Campaign atlas survey failed: {exc}") from exc
    return json.dumps(
        {
            "status": delivery.get("status"),
            "flow_id": FLOW_ID,
            "terminal": delivery["survey_result"]["terminal"],
            "session_directory": str(session),
            "dispatch": bool(delivery["survey_result"]["transport_dispatched"]),
            "navigation_inputs_used": delivery["survey_result"]["navigation_inputs_used"],
            "session_navigation_inputs_sent": delivery["survey_result"].get(
                "session_navigation_inputs_sent"
            ),
            "prior_continuation": delivery["survey_result"].get("prior_continuation"),
            "maximum_navigation_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
            "live_preflight_inadmissible": bool(
                delivery["survey_result"].get("live_preflight_inadmissible")
            ),
        },
        sort_keys=True,
    )


def verify_campaign_atlas_native_survey(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    pnsctl = _pnsctl()
    del lease
    result = structure["result"]
    if result.get("flow_id") != FLOW_ID:
        raise pnsctl.OperatorError("Campaign atlas survey evidence belongs to another flow")
    survey = result.get("survey_result") or {}
    terminal = survey.get("terminal")
    if terminal not in {
        "native_survey_complete",
        "evidence_required",
        "blocked_fail_closed",
        "unresolved",
    }:
        raise pnsctl.OperatorError("Campaign atlas survey terminal is not contract-recognized")
    used = int(survey.get("navigation_inputs_used") or 0)
    preflight_blocked = bool(survey.get("live_preflight_inadmissible"))
    if terminal == "native_survey_complete" and used == 0:
        raise pnsctl.OperatorError("complete survey cannot claim zero navigation inputs")
    if terminal == "evidence_required" and used == 0 and not preflight_blocked:
        raise pnsctl.OperatorError(
            "survey cannot claim evidence_required with zero navigation inputs "
            "unless live_preflight_inadmissible"
        )
    if terminal == "native_survey_complete":
        if result.get("terminal_runtime_state") != "recognized_home":
            raise pnsctl.OperatorError("complete survey must terminate at recognized_home")
        if not survey.get("transport_dispatched"):
            raise pnsctl.OperatorError("complete survey must have dispatched navigation transport")
    if terminal == "unresolved":
        if result.get("terminal_runtime_state") == "recognized_home":
            raise pnsctl.OperatorError("unresolved survey cannot claim recognized_home")
        if result.get("terminal_runtime_state") == "safe_blocked_terminal":
            raise pnsctl.OperatorError(
                "post-transport unresolved must not claim safe_blocked_terminal"
            )
    if preflight_blocked and survey.get("transport_dispatched"):
        raise pnsctl.OperatorError("live_preflight_inadmissible cannot claim transport_dispatched")
    ceiling = int(survey.get("maximum_navigation_inputs") or 0)
    if ceiling != ACTIVATED_TRANSPORT_INPUT_CEILING or used > ceiling:
        raise pnsctl.OperatorError("survey evidence violates the 272 navigation ceiling")
    if used == 0 and survey.get("transport_dispatched") and terminal == "blocked_fail_closed":
        raise pnsctl.OperatorError(
            "pre-input block cannot claim transport_dispatched without counted inputs"
        )
    session = Path(structure["session_directory"])
    report_path = session / str(survey.get("session_report_path") or "survey-session-report.json")
    if terminal in {"native_survey_complete", "evidence_required"} and report_path.is_file():
        report = report_from_dict(json.loads(report_path.read_text(encoding="utf-8")))
        validate_survey_session_report(report)
        if report.accounting.transport_inputs_used != used:
            session_sent = int(survey.get("session_navigation_inputs_sent") or 0)
            prior = survey.get("prior_continuation") or {}
            prior_seeded = int(prior.get("prior_inputs_seeded") or 0)
            delivery_accounting = survey.get("accounting") or {}
            # Seeded preflight: empty current-session journal/report; cumulative used is delivery-only.
            seeded_preflight_ok = (
                preflight_blocked
                and not bool(survey.get("transport_dispatched"))
                and report.accounting.transport_inputs_used == 0
                and session_sent == 0
                and used == prior_seeded
            )
            # Seeded complete: session report + evidence-backed prior == cumulative delivery.
            seeded_complete_ok = (
                terminal == "native_survey_complete"
                and bool(survey.get("transport_dispatched"))
                and _seeded_complete_accounting_reconciles(
                    report_accounting=report.accounting,
                    delivery_accounting=delivery_accounting
                    if isinstance(delivery_accounting, Mapping)
                    else {},
                    prior_continuation=prior if isinstance(prior, Mapping) else {},
                    cumulative_used=used,
                    session_sent=session_sent,
                )
            )
            if not seeded_preflight_ok and not seeded_complete_ok:
                raise pnsctl.OperatorError(
                    "survey session accounting does not match delivery result"
                )
        if any(item.authorizes_input for item in report.registration_residuals):
            raise pnsctl.OperatorError("registration residual must not authorize input")
        if terminal == "native_survey_complete":
            if report.loop_closure is None or not report.loop_closure.closed:
                raise pnsctl.OperatorError("complete survey requires closed loop-closure")
            if not report.overlaps or any(not item.associated for item in report.overlaps):
                raise pnsctl.OperatorError("complete survey requires associated progress overlaps")
            if report.safe_terminal is None or report.safe_terminal.terminal_state != "HOME_BASE":
                raise pnsctl.OperatorError("complete survey requires Home-bound safe terminal")
            if any(gap.unresolved for gap in report.coverage_gaps):
                raise pnsctl.OperatorError("complete survey forbids unresolved coverage gaps")
            if any(
                "outcome=no_progress" in str(item.notes)
                for item in report.overlaps
            ):
                raise pnsctl.OperatorError(
                    "serpentine no_progress clamps must not appear in overlap association reports"
                )
    return {
        "status": "verified",
        "flow_id": FLOW_ID,
        "terminal": terminal,
        "navigation_inputs_used": used,
        "live_preflight_inadmissible": preflight_blocked,
        "queue_flow_id": next(
            item["flow_id"] for item in queue["flows"] if item["flow_id"] == FLOW_ID
        ),
    }


def recover_campaign_atlas_native_survey(
    structure: Mapping[str, Any],
    queue: Mapping[str, Any],
    lease: Mapping[str, Any],
) -> dict[str, Any]:
    pnsctl = _pnsctl()
    del queue, lease
    result = structure.get("result") or {}
    survey = result.get("survey_result") or {}
    if survey.get("terminal") == "unresolved" or survey.get("unresolved"):
        raise pnsctl.OperatorError(
            "Campaign atlas survey unresolved; identical retry prohibited; "
            "reconcile retained SafeActionExecutor/journal evidence before any new input"
        )
    if survey.get("live_preflight_inadmissible"):
        raise pnsctl.OperatorError(
            "Campaign atlas survey live_preflight remains inadmissible: "
            + "; ".join(live_survey_preflight_blockers())
        )
    raise pnsctl.OperatorError("Campaign atlas survey recovery has no authorized retry path")


def _locate_unique_action_frame(session: Path, *, action_key: str, suffix: str) -> Path:
    frames_dir = session / "runtime" / "frames"
    if not frames_dir.is_dir():
        raise RuntimeError("survey session runtime frames directory is missing")
    matches = sorted(frames_dir.glob(f"*-{action_key}-{suffix}.png"))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one retained frame *-{action_key}-{suffix}.png; "
            f"found={len(matches)}"
        )
    return matches[0]


def _native_frame_hashes(path: Path) -> tuple[np.ndarray, str, str, int, int]:
    payload = path.read_bytes()
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"retained frame is not a PNG payload: {path.name}")
    transport = hashlib.sha256(payload).hexdigest()
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError(f"retained frame could not be decoded: {path.name}")
    height, width = frame.shape[:2]
    if (width, height) != (800, 1280):
        raise RuntimeError(
            f"retained frame is not native 800x1280: {path.name} ({width}x{height})"
        )
    semantic = frame_digest(frame)
    return frame, transport, semantic, width, height


def _load_offline_reconciliation_receipt(session: Path, *, action_key: str) -> dict[str, Any]:
    candidate = KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE
    if action_key != str(candidate["action_key"]):
        raise RuntimeError("offline reconciliation receipt action_key mismatch")
    if session.name != str(candidate["session_id"]):
        raise RuntimeError("offline reconciliation receipt session_id mismatch")
    receipt_path = session / str(candidate["receipt_name"])
    if not receipt_path.is_file():
        raise RuntimeError(
            "reconciled EDGE continuation requires an offline reconciliation receipt; "
            f"missing={receipt_path.name}"
        )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, Mapping):
        raise RuntimeError("offline reconciliation receipt is malformed")
    if str(receipt.get("receipt_kind") or "") != RECONCILIATION_RECEIPT_KIND:
        raise RuntimeError("offline reconciliation receipt_kind mismatch")
    if str(receipt.get("flow_id") or "") != FLOW_ID:
        raise RuntimeError("offline reconciliation receipt flow_id mismatch")
    if str(receipt.get("session_id") or "") != session.name:
        raise RuntimeError("offline reconciliation receipt session_id mismatch")
    if str(receipt.get("action_key") or "") != action_key:
        raise RuntimeError("offline reconciliation receipt action_key mismatch")
    if str(receipt.get("outcome") or "") != "progress":
        raise RuntimeError("offline reconciliation receipt outcome is not progress")
    if receipt.get("zero_input") is not True:
        raise RuntimeError("offline reconciliation receipt must declare zero_input")
    return dict(receipt)


def _verify_accepted_traversal_continuation_session(session: Path) -> dict[str, Any]:
    """Gate claimed=91 seed on accepted traversal accounting and terminal closure."""

    expected = KNOWN_CONTINUATION_TRAVERSAL_SESSION
    if session.name != str(expected["session_id"]):
        raise RuntimeError("traversal continuation session_id mismatch")
    if not session.is_dir():
        raise RuntimeError("traversal continuation session is missing")
    if survey_has_open_prepared_lifecycle(session):
        raise RuntimeError("traversal session has open prepared lifecycle; refuse seed")
    durable = load_durable_survey_accounting(session)
    if durable.get("open_prepared"):
        raise RuntimeError("traversal session accounting still open_prepared")
    if durable.get("unresolved"):
        raise RuntimeError("traversal session accounting remains unresolved")
    accounting = durable.get("accounting") or {}
    if int(accounting.get("transport_inputs_used") or 0) != int(
        expected["transport_inputs_used"]
    ):
        raise RuntimeError("traversal session transport_inputs_used mismatch")
    if int(accounting.get("auxiliary_used") or 0) != int(expected["auxiliary_used"]):
        raise RuntimeError("traversal session auxiliary_used mismatch")
    if int(accounting.get("edge_clamp_used") or 0) != int(expected["edge_clamp_used"]):
        raise RuntimeError("traversal session edge_clamp_used mismatch")
    if int(accounting.get("overlap_used") or 0) != int(expected["overlap_used"]):
        raise RuntimeError("traversal session overlap_used mismatch")
    if int(durable.get("session_navigation_inputs_sent") or 0) != int(
        expected["session_navigation_inputs_sent"]
    ):
        raise RuntimeError("traversal session_navigation_inputs_sent mismatch")
    if int(durable.get("prior_inputs_seeded") or 0) != int(
        expected["prior_inputs_seeded_inside_session"]
    ):
        raise RuntimeError("traversal prior_inputs_seeded inside session mismatch")
    # All lifecycle rows must be closed triples: prepared/input_sent/terminal.
    life_path = session / LIFECYCLE_PATH
    if not life_path.is_file():
        raise RuntimeError("traversal session lifecycle is missing")
    prepared = input_sent = terminal = 0
    last_terminal: str | None = None
    for line in life_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        lifecycle = str(event.get("lifecycle") or "")
        if lifecycle == InputLifecycle.PREPARED.value:
            prepared += 1
        elif lifecycle == InputLifecycle.INPUT_SENT.value:
            input_sent += 1
        elif lifecycle == InputLifecycle.TERMINAL.value:
            terminal += 1
            last_terminal = str(event.get("terminal") or "")
        elif lifecycle == InputLifecycle.UNRESOLVED.value:
            raise RuntimeError("traversal session has unresolved lifecycle row")
    if not (prepared == input_sent == terminal == int(expected["session_navigation_inputs_sent"])):
        raise RuntimeError(
            "traversal lifecycle prepared/input_sent/terminal counts mismatch "
            f"prepared={prepared} input_sent={input_sent} terminal={terminal}"
        )
    if last_terminal != "campaign-tier-1":
        raise RuntimeError(
            f"traversal last terminal must be campaign-tier-1; got={last_terminal}"
        )
    tier1_transport = session / "difficulty-tier-1-transport.json"
    tier1_result = session / "difficulty-tier-1-result.json"
    if not tier1_transport.is_file() or not tier1_result.is_file():
        raise RuntimeError("traversal session missing difficulty-tier-1 transport/result")
    if (session / "difficulty-tier-2-transport.json").is_file():
        raise RuntimeError("traversal session already has difficulty-tier-2 transport")
    skip_keys = sorted(
        path.name[: -len("-transport.json")]
        for path in session.glob("*-transport.json")
        if path.name.endswith("-transport.json")
    )
    if str(expected["completed_action_key"]) not in skip_keys:
        raise RuntimeError("traversal skip keys missing difficulty-tier-1")
    if str(expected["resume_action_key"]) in skip_keys:
        raise RuntimeError("traversal skip keys unexpectedly include difficulty-tier-2")
    post_rel = str(expected["retained_tier1_post_frame"])
    post_path = session / post_rel
    if not post_path.is_file():
        raise RuntimeError("retained tier1 post frame is missing")
    _frame, _transport, semantic, _w, _h = _native_frame_hashes(post_path)
    return {
        "session_id": session.name,
        "count": int(expected["transport_inputs_used"]),
        "terminal": "blocked_fail_closed_after_difficulty_tier_1",
        "category": KNOWN_CONTINUATION_TRAVERSAL_RESUME_CATEGORY,
        "prior_session_directory": str(session).replace("\\", "/"),
        "skip_prior_action_keys": skip_keys,
        "retained_tier1_post_sha256": semantic,
        "retained_tier1_post_frame": post_rel,
    }


def _verify_accepted_tier2_exit_continuation_session(session: Path) -> dict[str, Any]:
    """Gate claimed=92 seed on accepted tier2 AUX terminal without exit transport."""

    expected = KNOWN_CONTINUATION_TIER2_EXIT_SESSION
    if session.name != str(expected["session_id"]):
        raise RuntimeError("tier2-exit continuation session_id mismatch")
    if not session.is_dir():
        raise RuntimeError("tier2-exit continuation session is missing")
    if survey_has_open_prepared_lifecycle(session):
        raise RuntimeError("tier2-exit session has open prepared lifecycle; refuse seed")
    durable = load_durable_survey_accounting(session)
    if durable.get("open_prepared"):
        raise RuntimeError("tier2-exit session accounting still open_prepared")
    if durable.get("unresolved"):
        raise RuntimeError("tier2-exit session accounting remains unresolved")
    accounting = durable.get("accounting") or {}
    if int(accounting.get("transport_inputs_used") or 0) != int(
        expected["transport_inputs_used"]
    ):
        raise RuntimeError("tier2-exit session transport_inputs_used mismatch")
    if int(accounting.get("auxiliary_used") or 0) != int(expected["auxiliary_used"]):
        raise RuntimeError("tier2-exit session auxiliary_used mismatch")
    if int(accounting.get("edge_clamp_used") or 0) != int(expected["edge_clamp_used"]):
        raise RuntimeError("tier2-exit session edge_clamp_used mismatch")
    if int(accounting.get("overlap_used") or 0) != int(expected["overlap_used"]):
        raise RuntimeError("tier2-exit session overlap_used mismatch")
    if int(durable.get("session_navigation_inputs_sent") or 0) != int(
        expected["session_navigation_inputs_sent"]
    ):
        raise RuntimeError("tier2-exit session_navigation_inputs_sent mismatch")
    if int(durable.get("prior_inputs_seeded") or 0) != int(
        expected["prior_inputs_seeded_inside_session"]
    ):
        raise RuntimeError("tier2-exit prior_inputs_seeded inside session mismatch")
    life_path = session / LIFECYCLE_PATH
    if not life_path.is_file():
        raise RuntimeError("tier2-exit session lifecycle is missing")
    prepared = input_sent = terminal = 0
    last_terminal: str | None = None
    for line in life_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        lifecycle = str(event.get("lifecycle") or "")
        if lifecycle == InputLifecycle.PREPARED.value:
            prepared += 1
        elif lifecycle == InputLifecycle.INPUT_SENT.value:
            input_sent += 1
        elif lifecycle == InputLifecycle.TERMINAL.value:
            terminal += 1
            last_terminal = str(event.get("terminal") or "")
        elif lifecycle == InputLifecycle.UNRESOLVED.value:
            raise RuntimeError("tier2-exit session has unresolved lifecycle row")
    if not (prepared == input_sent == terminal == int(expected["session_navigation_inputs_sent"])):
        raise RuntimeError(
            "tier2-exit lifecycle prepared/input_sent/terminal counts mismatch "
            f"prepared={prepared} input_sent={input_sent} terminal={terminal}"
        )
    if last_terminal != "campaign-tier-2":
        raise RuntimeError(
            f"tier2-exit last terminal must be campaign-tier-2; got={last_terminal}"
        )
    tier2_transport = session / "difficulty-tier-2-transport.json"
    tier2_result = session / "difficulty-tier-2-result.json"
    if not tier2_transport.is_file() or not tier2_result.is_file():
        raise RuntimeError("tier2-exit session missing difficulty-tier-2 transport/result")
    if (session / "campaign-exit-home-transport.json").is_file():
        raise RuntimeError("tier2-exit session already has campaign-exit-home transport")
    # Union skip keys: traversal transports + this session's tier2 transport.
    traversal_session = (
        session.parent / str(expected["retained_traversal_session_id"])
    )
    if not traversal_session.is_dir():
        raise RuntimeError("retained traversal session missing for exit-only seed")
    skip_keys = sorted(
        {
            *(
                path.name[: -len("-transport.json")]
                for path in traversal_session.glob("*-transport.json")
                if path.name.endswith("-transport.json")
            ),
            *(
                path.name[: -len("-transport.json")]
                for path in session.glob("*-transport.json")
                if path.name.endswith("-transport.json")
            ),
        }
    )
    if str(expected["completed_action_key"]) not in skip_keys:
        raise RuntimeError("exit skip keys missing difficulty-tier-2")
    if "difficulty-tier-1" not in skip_keys:
        raise RuntimeError("exit skip keys missing difficulty-tier-1")
    if str(expected["resume_action_key"]) in skip_keys:
        raise RuntimeError("exit skip keys unexpectedly include campaign-exit-home")
    post_rel = str(expected["retained_tier2_post_frame"])
    post_path = session / post_rel
    if not post_path.is_file():
        raise RuntimeError("retained tier2 post frame is missing")
    _frame, _transport, semantic, _w, _h = _native_frame_hashes(post_path)
    return {
        "session_id": session.name,
        "count": int(expected["transport_inputs_used"]),
        "terminal": "blocked_fail_closed_after_difficulty_tier_2",
        "category": KNOWN_CONTINUATION_EXIT_RESUME_CATEGORY,
        "prior_session_directory": str(session).replace("\\", "/"),
        "skip_prior_action_keys": skip_keys,
        "retained_tier2_post_sha256": semantic,
        "retained_tier2_post_frame": post_rel,
        "retained_traversal_session_id": str(expected["retained_traversal_session_id"]),
    }


def _hydrate_retained_survey_completion_evidence(
    op: "_SurveyOperator",
    *,
    traversal_session: Path,
    tier2_session: Path,
) -> None:
    """Load retained coverage/difficulty/landmarks without fabricating journal rows."""

    if not traversal_session.is_dir() or not tier2_session.is_dir():
        raise RuntimeError("retained survey sessions missing for exit-only hydrate")
    edge_clamps: list[EdgeClampReport] = []
    for direction in _DIRECTIONS:
        matches = sorted(traversal_session.glob(f"annotations/edge-clamp-{direction}-*.json"))
        if not matches:
            raise RuntimeError(f"retained edge-clamp annotation missing for {direction}")
        payload = json.loads(matches[0].read_text(encoding="utf-8"))
        edge_clamps.append(
            EdgeClampReport(
                direction=direction,
                clamp_observed=True,
                supporting_frame_sha256=str(payload.get("source_sha256") or ""),
                notes=f"retained_annotation={matches[0].name}",
            )
        )
    if len(edge_clamps) < 4:
        raise RuntimeError("retained survey lacks four edge-clamp reports")
    overlaps: list[OverlapAssociationReport] = []
    for result_path in sorted(traversal_session.glob("overlap-*-result.json")):
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if str(payload.get("progress_outcome") or "") != "progress":
            continue
        overlaps.append(
            OverlapAssociationReport(
                reference_sha256=str(payload.get("reference_sha256") or ""),
                candidate_sha256=str(payload.get("candidate_sha256") or ""),
                overlap_ratio=float(payload.get("overlap_ratio") or 0.0),
                associated=True,
                notes=f"retained_result={result_path.name}",
            )
        )
    if not overlaps:
        raise RuntimeError("retained survey lacks progress overlap associations")
    # Offline remeasure loop closure from retained right-edge clamp vs loop-close post.
    right_post = traversal_session / "runtime" / "frames" / "0028-edge-right-05-post.png"
    loop_post = (
        traversal_session / "runtime" / "frames" / "0256-overlap-loop-close-061-post.png"
    )
    if not right_post.is_file() or not loop_post.is_file():
        raise RuntimeError("retained loop-closure frame pair is missing")
    right_frame, right_transport, right_semantic, right_w, right_h = _native_frame_hashes(
        right_post
    )
    loop_frame, loop_transport, loop_semantic, loop_w, loop_h = _native_frame_hashes(
        loop_post
    )
    right_prov = NativeFrameProvenance(
        source_id=str(right_post.as_posix()),
        capture_kind="fixture",
        runtime_session_id=traversal_session.name,
        capture_ordinal=1,
        capture_completed_monotonic=0.0,
        transport_sha256=right_transport,
        semantic_sha256=right_semantic,
        captured_at_utc=_utc_now(),
        width=right_w,
        height=right_h,
        profile_id=CAMPAIGN_PROFILE_ID,
        platform=CAMPAIGN_PLATFORM,
        package=CAMPAIGN_PACKAGE,
    )
    loop_prov = NativeFrameProvenance(
        source_id=str(loop_post.as_posix()),
        capture_kind="fixture",
        runtime_session_id=traversal_session.name,
        capture_ordinal=2,
        capture_completed_monotonic=0.0,
        transport_sha256=loop_transport,
        semantic_sha256=loop_semantic,
        captured_at_utc=_utc_now(),
        width=loop_w,
        height=loop_h,
        profile_id=CAMPAIGN_PROFILE_ID,
        platform=CAMPAIGN_PLATFORM,
        package=CAMPAIGN_PACKAGE,
    )
    loop_observation = measure_campaign_frame_pair(
        loop_frame,
        right_frame,
        candidate_provenance=loop_prov,
        reference_provenance=right_prov,
        backend=op.backend,
    )
    op.state.residuals.append(registration_residual_report(loop_observation))
    if not loop_closure_accepted(loop_observation.measurement):
        raise RuntimeError("retained loop-closure remeasure failed policy")
    # Offline remeasure cross-difficulty from retained tier1/tier2 posts.
    tier1_post = (
        traversal_session
        / str(KNOWN_CONTINUATION_TRAVERSAL_SESSION["retained_tier1_post_frame"])
    )
    tier2_post = (
        tier2_session / str(KNOWN_CONTINUATION_TIER2_EXIT_SESSION["retained_tier2_post_frame"])
    )
    if not tier1_post.is_file() or not tier2_post.is_file():
        raise RuntimeError("retained difficulty post frames missing for exit-only hydrate")
    t1_frame, t1_transport, t1_semantic, t1_w, t1_h = _native_frame_hashes(tier1_post)
    t2_frame, t2_transport, t2_semantic, t2_w, t2_h = _native_frame_hashes(tier2_post)
    t1_prov = NativeFrameProvenance(
        source_id=str(tier1_post.as_posix()),
        capture_kind="fixture",
        runtime_session_id=traversal_session.name,
        capture_ordinal=3,
        capture_completed_monotonic=0.0,
        transport_sha256=t1_transport,
        semantic_sha256=t1_semantic,
        captured_at_utc=_utc_now(),
        width=t1_w,
        height=t1_h,
        profile_id=CAMPAIGN_PROFILE_ID,
        platform=CAMPAIGN_PLATFORM,
        package=CAMPAIGN_PACKAGE,
    )
    t2_prov = NativeFrameProvenance(
        source_id=str(tier2_post.as_posix()),
        capture_kind="fixture",
        runtime_session_id=tier2_session.name,
        capture_ordinal=4,
        capture_completed_monotonic=0.0,
        transport_sha256=t2_transport,
        semantic_sha256=t2_semantic,
        captured_at_utc=_utc_now(),
        width=t2_w,
        height=t2_h,
        profile_id=CAMPAIGN_PROFILE_ID,
        platform=CAMPAIGN_PLATFORM,
        package=CAMPAIGN_PACKAGE,
    )
    difficulty_observation = measure_campaign_frame_pair(
        t2_frame,
        t1_frame,
        candidate_provenance=t2_prov,
        reference_provenance=t1_prov,
        backend=op.backend,
    )
    op.state.residuals.append(registration_residual_report(difficulty_observation))
    shared_geometry = overlap_association_accepted(difficulty_observation.measurement)
    landmarks: list[LandmarkBindingReport] = []
    for ann_path in sorted((tier2_session / "annotations").glob("*.json")):
        payload = json.loads(ann_path.read_text(encoding="utf-8"))
        label = str(payload.get("label") or "")
        digest = str(payload.get("source_sha256") or "")
        if label.startswith("campaign-chapter-"):
            number = label.rsplit("-", 1)[-1]
            landmarks.append(
                LandmarkBindingReport(
                    kind=LandmarkKind.CHAPTER,
                    label=f"Chapter {number}",
                    supporting_frame_sha256=digest,
                    spatially_associated=True,
                    notes=f"retained_annotation={ann_path.name}",
                )
            )
        elif label == "ultimate-challenge":
            landmarks.append(
                LandmarkBindingReport(
                    kind=LandmarkKind.ULTIMATE_CHALLENGE,
                    label="Ultimate Challenge",
                    supporting_frame_sha256=digest,
                    spatially_associated=True,
                    notes=f"retained_annotation={ann_path.name}",
                )
            )
        elif label == "prison-trial":
            landmarks.append(
                LandmarkBindingReport(
                    kind=LandmarkKind.PRISON_TRIAL,
                    label="Prison Trial",
                    supporting_frame_sha256=digest,
                    spatially_associated=True,
                    notes=f"retained_annotation={ann_path.name}",
                )
            )
    if not any(item.kind is LandmarkKind.CHAPTER for item in landmarks):
        raise RuntimeError("retained exit evidence lacks chapter landmark")
    if not any(
        item.kind in {LandmarkKind.PRISON_TRIAL, LandmarkKind.ULTIMATE_CHALLENGE}
        for item in landmarks
    ):
        raise RuntimeError("retained exit evidence lacks Prison/Ultimate landmark")
    op.state.edge_clamps = edge_clamps
    op.state.overlaps = overlaps
    op.state.loop_closure = LoopClosureReport(
        closed=True,
        residual_px=float(loop_observation.measurement.residual_px),
        supporting_frame_sha256=loop_semantic,
    )
    op.state.cross_difficulty = CrossDifficultyGeometryReport(
        difficulty_a=1,
        difficulty_b=2,
        compared=True,
        used_as_recenter=False,
        conclusion=(
            "shared_world_layout_and_coordinate_geometry"
            if shared_geometry
            else "different_or_unresolved_world_geometry"
        ),
    )
    op.state.landmarks = landmarks


def _verify_reconciled_edge_continuation_session(session: Path) -> dict[str, Any]:
    """Gate claimed=5 seed on an immutable offline reconciliation receipt."""

    candidate = KNOWN_CONTINUATION_RECONCILED_EDGE_CANDIDATE
    if session.name != str(candidate["session_id"]):
        raise RuntimeError("reconciled EDGE continuation session_id mismatch")
    if not session.is_dir():
        raise RuntimeError("reconciled EDGE continuation session is missing")
    action_key = str(candidate["action_key"])
    receipt = _load_offline_reconciliation_receipt(session, action_key=action_key)
    durable = load_durable_survey_accounting(session)
    if durable.get("open_prepared"):
        raise RuntimeError("reconciled EDGE session still has open prepared action")
    if durable.get("unresolved"):
        raise RuntimeError("reconciled EDGE session accounting remains unresolved")
    if int(durable.get("transport_inputs_used") or 0) < 1:
        raise RuntimeError("reconciled EDGE session has no durable transport")
    store_path = session / "campaign-atlas-survey-safety.sqlite3"
    if not store_path.is_file():
        raise RuntimeError("reconciled EDGE session SafetyStore is missing")
    store = SafetyStore(store_path)
    try:
        row = store.get_action_by_key(action_key)
        if row is None:
            raise RuntimeError("reconciled EDGE action_key is missing from SafetyStore")
        if str(row.get("final_status") or "") != ActionStatus.CONFIRMED.value:
            raise RuntimeError("reconciled EDGE SafetyStore action is not confirmed")
        if str(row.get("action_id") or "") != str(receipt.get("action_id") or ""):
            raise RuntimeError("reconciled EDGE receipt action_id mismatch")
    finally:
        store.close()
    return {
        "session_id": session.name,
        "count": KNOWN_CONTINUATION_RECONCILED_EDGE_COUNT,
        "terminal": str(candidate["terminal"]),
        "category": InputBudgetCategory.EDGE_CLAMP.value,
        "action_key": action_key,
        "receipt_path": str(candidate["receipt_name"]),
        "prior_session_directory": str(session).replace("\\", "/"),
    }


def reconcile_campaign_atlas_survey_action_offline(
    session: Path,
    *,
    action_key: str,
    expected_flow_id: str = FLOW_ID,
) -> dict[str, Any]:
    """Zero-input offline reconciliation for exactly one unresolved survey action.

    Recomputes production ``measure_campaign_frame_pair`` against retained native
    before/post frames, requires accepted ``progress``, applies SafetyStore
    ``reconcile_confirmed``, appends immutable receipts, and clears durable
    unresolved without rewriting historical evidence rows.
    """

    session = Path(session)
    if not session.is_dir():
        raise RuntimeError("survey session directory is missing")
    if expected_flow_id != FLOW_ID:
        raise RuntimeError("offline reconciliation flow_id mismatch")
    if session.parent.name != FLOW_ID:
        raise RuntimeError("survey session is not under the Campaign atlas flow artifact root")
    if not session.name.startswith("survey-"):
        raise RuntimeError("survey session identity is invalid")
    if not action_key or action_key != action_key.strip():
        raise RuntimeError("action_key is required")

    durable = load_durable_survey_accounting(session)
    if durable.get("open_prepared"):
        raise RuntimeError("refuse reconciliation while a prepared action remains open")
    if not durable.get("unresolved"):
        raise RuntimeError("survey accounting is not unresolved; refuse reinterpretation")
    if not durable.get("transport_dispatched"):
        raise RuntimeError("refuse reconciliation without dispatched transport")

    transport_path = session / f"{action_key}-transport.json"
    if not transport_path.is_file():
        raise RuntimeError("exact transport receipt is missing")
    transport = json.loads(transport_path.read_text(encoding="utf-8"))
    if not isinstance(transport, Mapping):
        raise RuntimeError("transport receipt is malformed")
    if str(transport.get("action_key") or "") != action_key:
        raise RuntimeError("transport receipt action_key mismatch")
    if str(transport.get("authority") or "") != "SafeActionExecutor":
        raise RuntimeError("transport receipt authority mismatch")
    if "swipe" not in transport and "tap_identity" not in transport:
        raise RuntimeError("transport receipt lacks dispatched gesture")

    lifecycle_path = session / LIFECYCLE_PATH
    if not lifecycle_path.is_file():
        raise RuntimeError("survey lifecycle is missing")
    input_sent_ordinals: set[int] = set()
    unresolved_ordinals: set[int] = set()
    prepared_open: set[int] = set()
    for line in lifecycle_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        ordinal = int(event.get("input_ordinal") or 0)
        lifecycle = str(event.get("lifecycle") or "")
        if lifecycle == InputLifecycle.PREPARED.value and ordinal > 0:
            prepared_open.add(ordinal)
        elif lifecycle == InputLifecycle.INPUT_SENT.value and ordinal > 0:
            prepared_open.discard(ordinal)
            input_sent_ordinals.add(ordinal)
        elif lifecycle in {InputLifecycle.TERMINAL.value, InputLifecycle.UNRESOLVED.value}:
            prepared_open.discard(ordinal)
            if lifecycle == InputLifecycle.UNRESOLVED.value:
                unresolved_ordinals.add(ordinal)
        elif lifecycle == "offline_reconciled" and ordinal > 0:
            prepared_open.discard(ordinal)
            unresolved_ordinals.discard(ordinal)
    if prepared_open:
        raise RuntimeError("refuse reconciliation while lifecycle has open prepared ordinals")
    if len(unresolved_ordinals) != 1:
        raise RuntimeError("exactly one unresolved lifecycle ordinal is required")
    if not input_sent_ordinals.intersection(unresolved_ordinals):
        raise RuntimeError("unresolved action lacks matching input_sent transport")

    before_path = _locate_unique_action_frame(
        session, action_key=action_key, suffix="immediate-before"
    )
    post_path = _locate_unique_action_frame(session, action_key=action_key, suffix="post")
    before_frame, before_transport, before_semantic, before_w, before_h = _native_frame_hashes(
        before_path
    )
    post_frame, post_transport, post_semantic, post_w, post_h = _native_frame_hashes(post_path)
    before_mtime = before_path.stat().st_mtime
    post_mtime = post_path.stat().st_mtime
    if not (post_mtime >= before_mtime):
        raise RuntimeError("immediate-post timestamp precedes immediate-before")

    before_prov = NativeFrameProvenance(
        source_id=str(before_path.as_posix()),
        capture_kind="fixture",
        runtime_session_id=session.name,
        capture_ordinal=1,
        capture_completed_monotonic=0.0,
        transport_sha256=before_transport,
        semantic_sha256=before_semantic,
        captured_at_utc="2026-07-24T00:00:00+00:00",
        width=before_w,
        height=before_h,
    )
    post_prov = NativeFrameProvenance(
        source_id=str(post_path.as_posix()),
        capture_kind="fixture",
        runtime_session_id=session.name,
        capture_ordinal=2,
        capture_completed_monotonic=1.0,
        transport_sha256=post_transport,
        semantic_sha256=post_semantic,
        captured_at_utc="2026-07-24T00:00:01+00:00",
        width=post_w,
        height=post_h,
    )
    observation = measure_campaign_frame_pair(
        post_frame,
        before_frame,
        candidate_provenance=post_prov,
        reference_provenance=before_prov,
        backend=OrbTranslationBackend(),
    )
    outcome = registration_progress_outcome(observation.measurement)
    if outcome == "no_progress":
        raise RuntimeError("offline reconciliation rejected clamp/no_progress measurement")
    if outcome != "progress":
        raise RuntimeError(
            f"offline reconciliation requires accepted progress; got={outcome}"
        )

    store_path = session / "campaign-atlas-survey-safety.sqlite3"
    if not store_path.is_file():
        raise RuntimeError("campaign atlas survey SafetyStore is missing")
    store = SafetyStore(store_path)
    try:
        if store.list_nonterminal_actions():
            raise RuntimeError("refuse reconciliation while SafetyStore has open prepared/input_sent")
        unresolved_rows = store.list_unresolved_actions(consequential_only=False)
        if len(unresolved_rows) != 1:
            raise RuntimeError("exactly one unresolved SafetyStore action is required")
        row = unresolved_rows[0]
        if str(row.get("action_key") or "") != action_key:
            raise RuntimeError("SafetyStore unresolved action_key mismatch")
        if str(row.get("task_id") or "") != FLOW_ID:
            raise RuntimeError("SafetyStore unresolved task_id mismatch")
        action_id = str(row["action_id"])
        transport_json = row.get("transport_result_json")
        if not transport_json:
            raise RuntimeError("SafetyStore unresolved action lacks transport receipt")
        transport_payload = (
            json.loads(transport_json) if isinstance(transport_json, str) else transport_json
        )
        if not isinstance(transport_payload, Mapping) or not transport_payload.get("dispatched"):
            raise RuntimeError("SafetyStore transport receipt is not dispatched")
        before_rel = _rel(session, before_path)
        post_rel = _rel(session, post_path)
        transport_rel = _rel(session, transport_path)
        positive_evidence = {
            "confirmed": True,
            "reason": "offline_measure_campaign_frame_pair_progress",
            "outcome": "progress",
            "zero_input": True,
            "flow_id": FLOW_ID,
            "session_id": session.name,
            "action_key": action_key,
            "action_id": action_id,
            "immediate_before_path": before_rel,
            "immediate_post_path": post_rel,
            "transport_record_path": transport_rel,
            "before_transport_sha256": before_transport,
            "before_semantic_sha256": before_semantic,
            "post_transport_sha256": post_transport,
            "post_semantic_sha256": post_semantic,
            "measurement": {
                "translation_px": float(observation.measurement.translation_px),
                "residual_px": float(observation.measurement.residual_px),
                "inliers": int(observation.measurement.inliers),
                "matches": int(observation.measurement.matches),
                "overlap_ratio": float(observation.measurement.overlap_ratio),
                "reason": observation.measurement.reason,
            },
        }
        store.reconcile_confirmed(action_id, time.time(), positive_evidence)
        store.audit(
            FLOW_ID,
            "campaign_atlas_survey_offline_reconciliation",
            time.time(),
            positive_evidence,
            action_id,
        )
    finally:
        store.close()

    receipt_name = f"{action_key}-offline-reconciliation.json"
    receipt_path = session / receipt_name
    if receipt_path.exists():
        raise RuntimeError("offline reconciliation receipt already exists; refuse rewrite")
    receipt = {
        "schema_version": 1,
        "receipt_kind": RECONCILIATION_RECEIPT_KIND,
        "flow_id": FLOW_ID,
        "session_id": session.name,
        "action_key": action_key,
        "action_id": action_id,
        "outcome": "progress",
        "zero_input": True,
        "safety_store_transition": "unresolved->confirmed",
        "immediate_before_path": before_rel,
        "immediate_post_path": post_rel,
        "transport_record_path": transport_rel,
        "before_transport_sha256": before_transport,
        "before_semantic_sha256": before_semantic,
        "post_transport_sha256": post_transport,
        "post_semantic_sha256": post_semantic,
        "measurement": positive_evidence["measurement"],
        "reconciled_at_utc": _utc_now(),
        "continuation_seed_after_receipt": {
            "claimed_navigation_inputs_used": KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE,
            "prior_auxiliary": KNOWN_CONTINUATION_PRIOR_COUNT,
            "prior_edge_clamp": KNOWN_CONTINUATION_RECONCILED_EDGE_COUNT,
            "remaining_transport": ACTIVATED_TRANSPORT_INPUT_CEILING
            - KNOWN_CONTINUATION_CUMULATIVE_WITH_RECONCILED_EDGE,
            "remaining_edge_clamp": ACTIVATED_EDGE_STEPS_TOTAL
            - KNOWN_CONTINUATION_RECONCILED_EDGE_COUNT,
            "remaining_auxiliary": ACTIVATED_AUXILIARY_INPUTS - KNOWN_CONTINUATION_PRIOR_COUNT,
            "queue_update_path": (
                "After this receipt exists, set queue flow navigation_inputs_used=5; "
                "next run seeds via resolve_evidence_backed_prior_auxiliary_seed(claimed=5)."
            ),
        },
    }
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    journal_receipt = {
        "receipt_kind": RECONCILIATION_RECEIPT_KIND,
        "input_ordinal": sorted(unresolved_ordinals)[0],
        "action_key": action_key,
        "lifecycle": "offline_reconciled",
        "terminal_classification": "progress",
        "evidence": {
            "immediate_before_path": before_rel,
            "immediate_post_path": post_rel,
            "transport_record_path": transport_rel,
            "semantic_result_path": receipt_name,
            "source_path": before_rel,
        },
        "historical_journal_preserved": True,
        "zero_input": True,
    }
    _append_jsonl(session / "journal.jsonl", journal_receipt)
    _append_jsonl(
        lifecycle_path,
        {
            "lifecycle": "offline_reconciled",
            "input_ordinal": sorted(unresolved_ordinals)[0],
            "action_key": action_key,
            "terminal": "progress",
            "unresolved": False,
            "receipt": receipt_name,
            "zero_input": True,
        },
    )
    # Update durable accounting unresolved without rewriting historical used counts.
    accounting_path = session / ACCOUNTING_PATH
    updated = dict(durable)
    updated["unresolved"] = False
    updated["open_prepared"] = False
    updated["offline_reconciliation_receipt"] = receipt_name
    updated["updated_at_utc"] = _utc_now()
    accounting_path.write_text(
        json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "status": "reconciled",
        "flow_id": FLOW_ID,
        "session_id": session.name,
        "action_key": action_key,
        "action_id": action_id,
        "outcome": "progress",
        "receipt": receipt_name,
        "zero_input": True,
        "immediate_before_path": before_rel,
        "immediate_post_path": post_rel,
        "continuation_seed_after_receipt": receipt["continuation_seed_after_receipt"],
    }


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
    handlers: dict[str, Any],
) -> None:
    runners[SURVEY_RUNNER_ID] = run_campaign_atlas_native_survey
    validators[SURVEY_EVIDENCE_VALIDATOR_ID] = verify_campaign_atlas_native_survey
    handlers[SURVEY_RECOVERY_HANDLER_ID] = recover_campaign_atlas_native_survey
