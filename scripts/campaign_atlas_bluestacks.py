"""Campaign atlas survey collector: prep dry-run plus activated session tooling.

Despite the platform-qualified filename, the default dry-run never opens ADB,
BlueStacks, Bliss, a subprocess, or any input transport. Activated live dispatch
is reserved for the pnsctl BlueStacks runner after parent admits live_execution.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tasks.campaign_atlas import (
    ACTIVATED_AUXILIARY_INPUTS,
    ACTIVATED_EDGE_STEPS_PER_DIRECTION,
    ACTIVATED_EDGE_STEPS_TOTAL,
    ACTIVATED_OVERLAP_STEPS,
    ACTIVATED_TRANSPORT_INPUT_CEILING,
    CollectorDisposition,
    ContractKind,
    CoverageGapReport,
    CrossDifficultyGeometryReport,
    EdgeClampReport,
    FrameClassification,
    FrameDisposition,
    FrameRejectionReason,
    InputBudgetAccounting,
    InputBudgetCategory,
    InputLifecycle,
    LandmarkBindingReport,
    LandmarkKind,
    LoopClosureReport,
    NativeFrameProvenance,
    NavigationEvidenceSequence,
    NavigationJournalEntry,
    OverlapAssociationReport,
    RegistrationResidualReport,
    SafeTerminalReport,
    SurveyPhase,
    SurveySessionManifest,
    SurveySessionReport,
    build_empty_activated_session_report,
    default_activated_scan_contract,
    default_prep_scan_contract,
    dry_run_campaign_survey,
    live_survey_preflight_blockers,
    validate_survey_session_report,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_dry_run_payload() -> dict[str, object]:
    report = dry_run_campaign_survey(default_prep_scan_contract())
    return report.to_dict()


def build_activated_contract_payload() -> dict[str, object]:
    contract = default_activated_scan_contract()
    return {
        "contract_kind": contract.contract_kind.value,
        "maximum_edge_steps_per_direction": contract.maximum_edge_steps_per_direction,
        "maximum_edge_steps_total": ACTIVATED_EDGE_STEPS_TOTAL,
        "maximum_overlapping_viewports": contract.maximum_overlapping_viewports,
        "maximum_auxiliary_inputs": contract.maximum_auxiliary_inputs,
        "maximum_transport_inputs": contract.maximum_transport_inputs,
        "maximum_sessions": contract.maximum_sessions,
        "difficulty_switch_policy": contract.difficulty_switch_policy,
        "build_atlas": contract.build_atlas,
        "phases": [phase.value for phase in contract.phases],
        "budget_partitions": {
            "edge_clamp": ACTIVATED_EDGE_STEPS_TOTAL,
            "overlap": ACTIVATED_OVERLAP_STEPS,
            "auxiliary_entry_difficulty_terminal_recovery": ACTIVATED_AUXILIARY_INPUTS,
            "total": ACTIVATED_TRANSPORT_INPUT_CEILING,
        },
        "edge_steps_per_direction": ACTIVATED_EDGE_STEPS_PER_DIRECTION,
        "transport_dispatched": False,
    }


def report_from_dict(payload: dict[str, Any]) -> SurveySessionReport:
    manifest_raw = payload["manifest"]
    manifest = SurveySessionManifest(
        schema_version=int(manifest_raw["schema_version"]),
        flow_id=str(manifest_raw["flow_id"]),
        session_id=str(manifest_raw["session_id"]),
        contract_kind=ContractKind(str(manifest_raw["contract_kind"])),
        profile_id=str(manifest_raw["profile_id"]),
        platform=str(manifest_raw["platform"]),
        package=str(manifest_raw["package"]),
        mask_contract_id=str(manifest_raw["mask_contract_id"]),
        native_width=int(manifest_raw["native_width"]),
        native_height=int(manifest_raw["native_height"]),
        maximum_transport_inputs=int(manifest_raw["maximum_transport_inputs"]),
        maximum_sessions=int(manifest_raw["maximum_sessions"]),
        session_index=int(manifest_raw["session_index"]),
        created_at_utc=str(manifest_raw["created_at_utc"]),
        difficulty_switch_policy=str(manifest_raw["difficulty_switch_policy"]),
        registration_authorizes_input=bool(manifest_raw["registration_authorizes_input"]),
    )
    accounting_raw = payload["accounting"]
    accounting = InputBudgetAccounting(
        edge_clamp_used=int(accounting_raw["edge_clamp_used"]),
        overlap_used=int(accounting_raw["overlap_used"]),
        auxiliary_used=int(accounting_raw["auxiliary_used"]),
        maximum_edge_clamp=int(accounting_raw["maximum_edge_clamp"]),
        maximum_overlap=int(accounting_raw["maximum_overlap"]),
        maximum_auxiliary=int(accounting_raw["maximum_auxiliary"]),
    )
    accepted = tuple(
        FrameClassification(
            disposition=FrameDisposition.ACCEPTED,
            provenance=NativeFrameProvenance(**item["provenance"]),
            mask_contract_id=str(item["mask_contract_id"]),
        )
        for item in payload.get("accepted_frames", [])
    )
    rejected = tuple(
        FrameClassification(
            disposition=FrameDisposition.REJECTED,
            provenance=None,
            mask_contract_id=str(item.get("mask_contract_id") or ""),
            rejection_reason=FrameRejectionReason(str(item["rejection_reason"])),
            notes=str(item.get("notes") or ""),
        )
        for item in payload.get("rejected_frames", [])
    )
    journal = tuple(
        NavigationJournalEntry(
            input_ordinal=int(item["input_ordinal"]),
            phase=SurveyPhase(str(item["phase"])),
            budget_category=InputBudgetCategory(str(item["budget_category"])),
            evidence=NavigationEvidenceSequence(**item["evidence"]),
            terminal_classification=str(item["terminal_classification"]),
            identical_retry=bool(item.get("identical_retry", False)),
            lifecycle=InputLifecycle(str(item.get("lifecycle", "terminal"))),
            prior_progress_proven=bool(item.get("prior_progress_proven", False)),
            swipe_geometry=tuple(item["swipe_geometry"])
            if item.get("swipe_geometry")
            else None,
        )
        for item in payload.get("journal", [])
    )
    loop_raw = payload.get("loop_closure")
    cross_raw = payload.get("cross_difficulty")
    safe_raw = payload.get("safe_terminal")
    report = SurveySessionReport(
        manifest=manifest,
        accounting=accounting,
        accepted_frames=accepted,
        rejected_frames=rejected,
        journal=journal,
        edge_clamps=tuple(EdgeClampReport(**item) for item in payload.get("edge_clamps", [])),
        overlaps=tuple(
            OverlapAssociationReport(**item) for item in payload.get("overlaps", [])
        ),
        registration_residuals=tuple(
            RegistrationResidualReport(**item)
            for item in payload.get("registration_residuals", [])
        ),
        coverage_gaps=tuple(
            CoverageGapReport(**item) for item in payload.get("coverage_gaps", [])
        ),
        loop_closure=None if loop_raw is None else LoopClosureReport(**loop_raw),
        cross_difficulty=None
        if cross_raw is None
        else CrossDifficultyGeometryReport(**cross_raw),
        landmarks=tuple(
            LandmarkBindingReport(
                kind=LandmarkKind(str(item["kind"])),
                label=str(item["label"]),
                supporting_frame_sha256=str(item["supporting_frame_sha256"]),
                spatially_associated=bool(item["spatially_associated"]),
                notes=str(item.get("notes") or ""),
            )
            for item in payload.get("landmarks", [])
        ),
        safe_terminal=None if safe_raw is None else SafeTerminalReport(**safe_raw),
        disposition=CollectorDisposition(str(payload["disposition"])),
        reason=str(payload["reason"]),
        transport_dispatched=bool(payload["transport_dispatched"]),
    )
    validate_survey_session_report(report)
    return report


def validate_session_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("session report must be a JSON object")
    report = report_from_dict(payload)
    return {
        "status": "validated",
        "session_id": report.manifest.session_id,
        "disposition": report.disposition.value,
        "transport_inputs_used": report.accounting.transport_inputs_used,
        "maximum_transport_inputs": report.accounting.maximum_transport_inputs,
        "transport_dispatched": report.transport_dispatched,
        "accepted_frames": len(report.accepted_frames),
        "rejected_frames": len(report.rejected_frames),
        "journal_entries": len(report.journal),
    }


def build_activated_survey_readiness_payload(
    *,
    session_id: str | None = None,
    execute: bool = False,
) -> dict[str, object]:
    """Offline activated readiness. Never dispatches transport from this module alone."""

    if execute:
        return {
            "disposition": CollectorDisposition.BLOCKED_FAIL_CLOSED.value,
            "reason": (
                "campaign_atlas_bluestacks activated-survey refuses direct --execute; "
                "live dispatch is only available through scripts/pnsctl.py bluestacks run-flow"
            ),
            "transport_dispatched": False,
            "transport_input_count": 0,
            "maximum_transport_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
            "contract": build_activated_contract_payload(),
        }
    session = session_id or f"campaign-atlas-survey-ready-{_utc_now()}"
    report = build_empty_activated_session_report(
        session_id=session,
        created_at_utc=_utc_now(),
    )
    return {
        "disposition": report.disposition.value,
        "reason": report.reason,
        "transport_dispatched": False,
        "transport_input_count": 0,
        "maximum_transport_inputs": ACTIVATED_TRANSPORT_INPUT_CEILING,
        "session_report": report.to_dict(),
        "contract": build_activated_contract_payload(),
        "reuse_seams": {
            "home_to_campaign_entry": (
                "scripts.home_atlas_bluestacks.run_verified_campaign_home_atlas_entry"
            ),
            "campaign_recognizer": (
                "tasks.campaign_auto_battle_vision.recognize_campaign_frame"
            ),
            "hud_safe_pan": "tasks.campaign_atlas_vision.hud_safe_pan_gesture",
            "registration_measurement": (
                "tasks.campaign_atlas_vision.measure_campaign_frame_pair"
            ),
            "input_authority": "registration_measurement_never_authorizes_input",
            "live_runner": "scripts.flow_delivery_campaign_atlas_bluestacks.run_bounded_campaign_atlas_survey",
        },
        "live_interface": (
            "python scripts/pnsctl.py bluestacks run-flow "
            "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION"
        ),
        "live_preflight_admissible": False,
        "live_preflight_blockers": list(live_survey_preflight_blockers()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "dry-run",
        help="validate the zero-input prep evidence gate without collecting frames",
    )
    sub.add_parser(
        "show-activated-contract",
        help="print the activated 272-input scan contract without transport",
    )
    activated = sub.add_parser(
        "activated-survey",
        help="print activated session readiness; refuse direct live execute",
    )
    activated.add_argument("--session-id", default=None)
    activated.add_argument(
        "--execute",
        action="store_true",
        help="rejected here; live dispatch is pnsctl-only",
    )
    validate = sub.add_parser(
        "validate-session",
        help="validate a session report JSON against activated schemas",
    )
    validate.add_argument("session_report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "dry-run":
        print(json.dumps(build_dry_run_payload(), indent=2, sort_keys=True))
        return 0
    if args.command == "show-activated-contract":
        print(json.dumps(build_activated_contract_payload(), indent=2, sort_keys=True))
        return 0
    if args.command == "activated-survey":
        payload = build_activated_survey_readiness_payload(
            session_id=args.session_id,
            execute=bool(args.execute),
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.execute and payload.get("disposition") == "blocked_fail_closed":
            return 1
        return 0
    if args.command == "validate-session":
        print(
            json.dumps(
                validate_session_payload(args.session_report),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
