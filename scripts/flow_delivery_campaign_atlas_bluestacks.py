#!/usr/bin/env python3
"""Checked-in BlueStacks operator for Campaign atlas native survey delivery.

Crash-safe lifecycle: prepared -> SafeActionExecutor transport -> input_sent
(+budget) -> terminal|unresolved. Direct LocalBlueStacksRuntime.swipe/tap is
never the action authority. No static ROI taps. Overlap spend blocked while
association policy is absent. Live preflight remains inadmissible until
evidence gaps close.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
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
from scripts.home_atlas_bluestacks import (
    gesture_geometry_roi,
    require_campaign_home_atlas_building,
    run_verified_campaign_home_atlas_entry,
)
from tasks.campaign_atlas import (
    ACTIVATED_EDGE_STEPS_PER_DIRECTION,
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
    hud_safe_pan_gesture,
    measure_campaign_frame_pair,
    measured_content_annotation_roi,
    prison_trial_roi_from_strong_spatial_evidence,
    registration_progress_outcome,
    registration_residual_report,
    require_measured_nonstatic_survey_target,
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
_SURVEY_TRANSPORT_SEAL = object()
SURVEY_PAN_SEMANTIC_ACTION = "CAMPAIGN_ATLAS_MAP_PAN"
SURVEY_TAP_SEMANTIC_ACTION = "CAMPAIGN_ATLAS_MAP_TAP"
SURVEY_PAN_POSTCONDITION = "CAMPAIGN_TIER_MAP_VIEWPORT_PROGRESS"
SURVEY_TAP_POSTCONDITION = "CAMPAIGN_NAVIGATION_SUCCESSOR"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pnsctl():
    from scripts import pnsctl

    return pnsctl


def production_survey_call_graph() -> dict[str, str]:
    return {
        "home_to_campaign_entry": "scripts.home_atlas_bluestacks.run_verified_campaign_home_atlas_entry",
        "safe_action_executor": "safe_action_core.SafeActionExecutor",
        "campaign_recognizer": "tasks.campaign_auto_battle_vision.recognize_campaign_frame",
        "hud_safe_pan": "tasks.campaign_atlas_vision.hud_safe_pan_gesture",
        "registration_measurement": "tasks.campaign_atlas_vision.measure_campaign_frame_pair",
        "ultimate_landmark_bind": "tasks.ultimate_challenge_daily.recognize_ultimate_challenge_entry_from_texts",
        "operator_interface": "scripts.pnsctl.bluestacks_run_flow",
    }


def _require_survey_budget(flow: Mapping[str, Any]) -> None:
    pnsctl = _pnsctl()
    if int(flow.get("maximum_navigation_inputs") or 0) != ACTIVATED_TRANSPORT_INPUT_CEILING:
        raise pnsctl.OperatorError("Campaign atlas survey ceiling must be exactly 272")
    if int(flow.get("navigation_inputs_used") or 0) != 0 and flow.get(
        "navigation_budget_disposition"
    ) == "explicitly_authorized_not_started":
        raise pnsctl.OperatorError("survey accounting is inconsistent before first input")
    if int(flow.get("maximum_live_attempts") or 0) != 1:
        raise pnsctl.OperatorError("Campaign atlas survey allows exactly one live session")
    if int(flow.get("live_attempt_count") or 0) >= 1:
        raise pnsctl.OperatorError("Campaign atlas survey session budget already consumed")


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
    recognition: Any, identity: str
) -> tuple[int, int, int, int]:
    """Fail closed unless identity has current-frame measured non-static geometry."""

    return require_measured_nonstatic_survey_target(recognition, identity)


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


def _provenance_for(
    path: Path,
    *,
    session_id: str,
    ordinal: int,
    monotonic: float,
    digest: str,
) -> NativeFrameProvenance:
    return NativeFrameProvenance(
        source_id=str(path.as_posix()),
        capture_kind="live",
        runtime_session_id=session_id,
        capture_ordinal=ordinal,
        capture_completed_monotonic=monotonic,
        transport_sha256=digest,
        semantic_sha256=digest,
        captured_at_utc=_utc_now(),
        width=800,
        height=1280,
        profile_id=CAMPAIGN_PROFILE_ID,
        platform=CAMPAIGN_PLATFORM,
        package=CAMPAIGN_PACKAGE,
    )


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True, default=str) + "\n")


def _write_accounting(session: Path, state: "_SurveyState") -> None:
    counted = sum(
        1
        for entry in state.journal
        if entry.lifecycle is not InputLifecycle.PREPARED
    )
    used = max(state.accounting.transport_inputs_used, counted)
    open_prepared = any(entry.lifecycle is InputLifecycle.PREPARED for entry in state.journal)
    payload = {
        "transport_inputs_used": used,
        "accounting": state.accounting.to_dict(),
        "unresolved": state.unresolved or open_prepared,
        "transport_dispatched": state.transport_dispatched or used > 0,
        "open_prepared": open_prepared,
        "journal_len": len(state.journal),
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
    ) -> None:
        self.session = session
        self.runtime = runtime
        self.session_id = session_id
        self.lease_owner = lease_owner
        self.backend = OrbTranslationBackend()
        self.state = _SurveyState(accounting=InputBudgetAccounting())
        self.lifecycle_path = session / LIFECYCLE_PATH
        self.journal_path = session / "journal.jsonl"
        self.events_path = session / "events.jsonl"
        self.policy = CentralPolicy(supervised_tasks=frozenset({FLOW_ID, "MVP-QUEST-TO-CLAIM"}))
        self.store = SafetyStore(session / "campaign-atlas-survey-safety.sqlite3")
        self.store.acquire_lease(lease_owner, time.time(), 3600.0)
        for path in (
            self.lifecycle_path,
            self.journal_path,
            self.events_path,
            session / "ledger.jsonl",
            session / "capability-audit.jsonl",
        ):
            if not path.exists():
                path.write_text("", encoding="utf-8")
        _write_accounting(session, self.state)

    def close(self) -> None:
        self.store.close()

    def capture(self, label: str):
        frame = self.runtime.capture(label)
        self.state.capture_ordinal += 1
        prov = _provenance_for(
            frame.path,
            session_id=self.session_id,
            ordinal=self.state.capture_ordinal,
            monotonic=frame.captured_monotonic,
            digest=frame.sha256,
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
        post_observe_fn,
        reconcile_fn,
    ):
        action_id = f"{FLOW_ID}:{action_key}:{uuid.uuid4().hex[:12]}"
        now = time.monotonic()
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
                f"SafeActionExecutor capability denied for {action_key}: {issued.reason}"
            )
        proposal = replace(
            observation,
            capture_completed_monotonic=observation.capture_completed_monotonic - 0.05,
        )

        def recapture() -> Observation:
            rebuilt = replace(observation)
            if rebuilt is observation:
                rebuilt = replace(
                    observation,
                    evidence_refs=observation.evidence_refs + ("recapture",),
                )
            return rebuilt

        executor = SafeActionExecutor(
            self.store,
            self.policy,
            self.lease_owner,
            time.monotonic,
            transport_fn,
            recapture,
            post_observe_fn,
            reconcile_fn,
            wall_clock=time.time,
            max_pre_dispatch_attempts=1,
        )
        execute_request = _build_survey_policy_request(
            observation=proposal,
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
    ) -> tuple[Any, Any, str]:
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
            before_rel=before_rel,
            transport_rel=transport_rel,
            source_rel=source_rel,
            swipe=swipe,
            prior_progress_proven=prior_progress_proven,
            planned_terminal=target_identity,
        )
        drag_start = (swipe[0], swipe[1])
        drag_end = (swipe[2], swipe[3])
        observation = _build_survey_observation(
            frame_sha256=before.sha256,
            capture_completed_monotonic=before.captured_monotonic,
            target_identity=target_identity,
            target_roi=gesture_geometry_roi(drag_start, drag_end),
            semantic_action=SURVEY_PAN_SEMANTIC_ACTION,
            expected_postcondition=SURVEY_PAN_POSTCONDITION,
        )
        post_holder: dict[str, Any] = {}

        def transport_fn(_intent) -> TransportResult:
            reject_direct_survey_transport(authorized_token=_SURVEY_TRANSPORT_SEAL)
            self.runtime.swipe(
                before,
                start=drag_start,
                end=drag_end,
                action_key=action_key,
                target_identity=target_identity,
            )
            return TransportResult(True, "CAMPAIGN_ATLAS_PAN_DISPATCHED")

        def post_observe():
            time.sleep(0.7)
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
            return True

        try:
            self._execute_via_safe_action(
                observation=observation,
                action_key=action_key,
                semantic_action=SURVEY_PAN_SEMANTIC_ACTION,
                transport_fn=transport_fn,
                post_observe_fn=post_observe,
                reconcile_fn=reconcile,
            )
        except Exception as exc:
            self.mark_terminal(
                ordinal,
                evidence=NavigationEvidenceSequence(
                    source_path=source_rel,
                    immediate_before_path=before_rel,
                    transport_record_path=transport_rel,
                    immediate_post_path=before_rel,
                    semantic_result_path=transport_rel,
                ),
                terminal=f"unresolved_safe_action:{exc}",
                unresolved=True,
            )
            raise
        self.mark_input_sent(ordinal, category=category)
        post = post_holder["post"]
        post_prov = post_holder["post_prov"]
        observation_meas = measure_campaign_frame_pair(
            post.frame,
            before.frame,
            candidate_provenance=post_prov,
            reference_provenance=before_prov,
            backend=self.backend,
        )
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
            immediate_before_path=before_rel,
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
        return post, post_prov, outcome

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
    ) -> tuple[Any, Any]:
        recognition = self.recognize(before.frame)
        roi = require_bound_survey_target(recognition, identity)
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
            before_rel=before_rel,
            transport_rel=transport_rel,
            source_rel=source_rel,
            swipe=None,
            prior_progress_proven=False,
            planned_terminal=identity,
        )
        observation = _build_survey_observation(
            frame_sha256=before.sha256,
            capture_completed_monotonic=before.captured_monotonic,
            target_identity=identity,
            target_roi=roi,
            semantic_action=SURVEY_TAP_SEMANTIC_ACTION,
            expected_postcondition=SURVEY_TAP_POSTCONDITION,
        )
        post_holder: dict[str, Any] = {}

        def transport_fn(_intent) -> TransportResult:
            reject_direct_survey_transport(authorized_token=_SURVEY_TRANSPORT_SEAL)
            self.runtime.tap(
                before,
                target_identity=identity,
                target_roi=roi,
                action_key=action_key,
                consequential=False,
            )
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
            return True

        try:
            self._execute_via_safe_action(
                observation=observation,
                action_key=action_key,
                semantic_action=SURVEY_TAP_SEMANTIC_ACTION,
                transport_fn=transport_fn,
                post_observe_fn=post_observe,
                reconcile_fn=reconcile,
            )
        except Exception as exc:
            self.mark_terminal(
                ordinal,
                evidence=NavigationEvidenceSequence(
                    source_path=source_rel,
                    immediate_before_path=before_rel,
                    transport_record_path=transport_rel,
                    immediate_post_path=before_rel,
                    semantic_result_path=transport_rel,
                ),
                terminal=f"unresolved_safe_action:{exc}",
                unresolved=True,
            )
            raise
        self.mark_input_sent(ordinal, category=category)
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
            self.session, before.frame, label=identity, roi=roi, digest=before.sha256
        )
        self.state.annotation_paths.append(ann)
        evidence = NavigationEvidenceSequence(
            source_path=source_rel,
            immediate_before_path=before_rel,
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
) -> dict[str, Any]:
    blockers = list(live_survey_preflight_blockers())
    reason = "; ".join(blockers)
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
    (session / ACCOUNTING_PATH).write_text(
        json.dumps(
            {
                "transport_inputs_used": 0,
                "unresolved": False,
                "transport_dispatched": False,
                "open_prepared": False,
                "journal_len": 0,
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
            "navigation_inputs_used": 0,
            "maximum_navigation_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
            "session_report_path": "survey-session-report.json",
            "frame_classification_path": FRAME_CLASSIFICATION_PATH,
            "live_preflight_inadmissible": True,
            "preflight_blockers": blockers,
            "unresolved": False,
            "call_graph": production_survey_call_graph(),
        },
        "actions": [
            {
                "action_class": "navigation_only",
                "outcome": "evidence_required",
                "transport_dispatched": False,
                "navigation_inputs_used": 0,
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
) -> dict[str, Any]:
    require_campaign_home_atlas_building(DEFAULT_HOME_ATLAS)
    # Finding 4/5: without measured non-static selectors and overlap association
    # policy, live traversal cannot meet task value. Stop pre-input.
    if not live_survey_preflight_is_admissible():
        return _preflight_blocked_delivery(
            session=session, serial=serial, runtime_owner=runtime_owner
        )

    runner = ADBRunner(adb, serial)
    runtime = LocalBlueStacksRuntime(runner, session / "runtime", execute=True)
    session_id = f"campaign-atlas-survey-{session.name}"
    op = _SurveyOperator(session, runtime, session_id, lease_owner=runtime_owner)
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
        before, _ = op.capture("entry-immediate-before")
        if op.recognize(before.frame).observation.screen != CampaignScreen.HOME_BASE:
            raise RuntimeError(
                f"unsupported survey start screen: {op.recognize(before.frame).observation.screen.value}"
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

    for direction in _DIRECTIONS:
        gesture = hud_safe_pan_gesture(direction)
        swipe = gesture.as_swipe()
        clamped = False
        for step in range(ACTIVATED_EDGE_STEPS_PER_DIRECTION):
            before, before_prov = op.capture(f"edge-{direction}-before-{step:02d}")
            if op.recognize(before.frame).observation.screen != CampaignScreen.TIER_MAP:
                raise RuntimeError(f"left TIER_MAP during {direction} edge survey")
            prior = op.state.last_progress_proven if op.state.last_swipe == swipe else False
            post, _post_prov, outcome = op.dispatch_swipe(
                phase=_PHASE_FOR_DIRECTION[direction],
                category=InputBudgetCategory.EDGE_CLAMP,
                source_rel=source_rel,
                before=before,
                before_prov=before_prov,
                before_rel=_rel(session, before.path),
                swipe=swipe,
                action_key=f"edge-{direction}-{step:02d}",
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

    # Do not spend overlap inputs without association/coverage policy.
    op.state.coverage_gaps.append(
        CoverageGapReport(
            gap_id="overlap_association_policy",
            description=(
                "overlap traversal withheld; association/coverage policy absent; "
                "no overlap budget spent"
            ),
            unresolved=True,
        )
    )

    # Difficulty / exit taps require measured non-static geometry; refuse static.
    before, _ = op.capture("difficulty-tier-1-before")
    if op.recognize(before.frame).observation.screen != CampaignScreen.TIER_MAP:
        raise RuntimeError("TIER_MAP required before difficulty comparison")
    raise RuntimeError(
        "evidence_required: difficulty/exit/base taps refused; "
        "recognizer boxes are compile-time static ROIs without current-frame measured geometry"
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
    disposition = CollectorDisposition.EVIDENCE_REQUIRED
    reason = (
        "bounded survey retained measurements; "
        "loop_closure/overlap_association/shared_difficulty_geometry remain evidence_required"
    )
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
        accounting=op.state.accounting,
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
            "terminal": "evidence_required",
            "reason": reason,
            "transport_dispatched": True,
            "navigation_inputs_used": op.state.accounting.transport_inputs_used,
            "maximum_navigation_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
            "session_report_path": "survey-session-report.json",
            "frame_classification_path": classification_path,
            "accounting": op.state.accounting.to_dict(),
            "unresolved": op.state.unresolved,
            "annotations": list(op.state.annotation_paths),
            "call_graph": production_survey_call_graph(),
        },
        "actions": [
            {
                "action_class": "navigation_only",
                "outcome": "evidence_required",
                "transport_dispatched": True,
                "navigation_inputs_used": op.state.accounting.transport_inputs_used,
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
    transported = bool(durable.get("transport_dispatched")) or used > 0 or open_prepared
    unresolved = bool(durable.get("unresolved")) or transported or open_prepared
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
            "maximum_navigation_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
            "session_report_path": "survey-session-report.json",
            "unresolved": unresolved,
            "open_prepared": open_prepared,
            "durable_accounting": durable,
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
    stamp = _utc_stamp()
    session = pnsctl.BLUESTACKS_ARTIFACT_ROOT / FLOW_ID / f"survey-{stamp}"
    session.mkdir(parents=True, exist_ok=False)
    try:
        delivery = run_bounded_campaign_atlas_survey(
            session=session,
            adb=str(pnsctl.BLUESTACKS_ADB),
            serial=pnsctl.BLUESTACKS_SERIAL,
            runtime_owner=str(lease["owner"]),
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
            raise pnsctl.OperatorError("survey session accounting does not match delivery result")
        if any(item.authorizes_input for item in report.registration_residuals):
            raise pnsctl.OperatorError("registration residual must not authorize input")
        if terminal == "native_survey_complete":
            if report.loop_closure is None or not report.loop_closure.closed:
                raise pnsctl.OperatorError("complete survey requires closed loop-closure")
            if any(not item.associated for item in report.overlaps):
                raise pnsctl.OperatorError("complete survey requires associated overlaps")
            if any(gap.unresolved for gap in report.coverage_gaps):
                raise pnsctl.OperatorError("complete survey forbids unresolved coverage gaps")
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


def register(
    runners: dict[str, Any],
    validators: dict[str, Any],
    handlers: dict[str, Any],
) -> None:
    runners[SURVEY_RUNNER_ID] = run_campaign_atlas_native_survey
    validators[SURVEY_EVIDENCE_VALIDATOR_ID] = verify_campaign_atlas_native_survey
    handlers[SURVEY_RECOVERY_HANDLER_ID] = recover_campaign_atlas_native_survey
