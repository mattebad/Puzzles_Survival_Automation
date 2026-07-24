"""Stage-9 recognition provenance for Campaign AP destinations.

Stage 9 is authorized only from retained native chapter-map ground truth with independent
source hash, crop ROI, template hash, runtime profile, annotated source, and nearby semantic
association. Filenames, synthetic images, production constants, and circular fixtures do not
prove Stage-9 identity. Missing chapter evidence remains evidence_required with zero transport.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from tasks.campaign_atlas import CAMPAIGN_PROFILE_ID
from tasks.campaign_auto_battle import (
    SUPPORTED_CAMPAIGN_STORY_DESTINATIONS,
    CampaignScreen,
    parse_supported_campaign_story_destination,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE9_GROUND_TRUTH_ROOT = (
    REPO_ROOT
    / "tasks"
    / "assets"
    / "campaign_auto_battle"
    / "800x1280"
    / "ground-truth"
)
STAGE9_CHAPTER20_MANIFEST = STAGE9_GROUND_TRUTH_ROOT / "stage-9-chapter-20" / "manifest.json"
STAGE9_CHAPTER15_MANIFEST = STAGE9_GROUND_TRUTH_ROOT / "stage-9-chapter-15" / "manifest.json"
STAGE9_CHAPTER2_MANIFEST = STAGE9_GROUND_TRUTH_ROOT / "stage-9-chapter-2" / "manifest.json"
DEFAULT_STAGE9_MANIFESTS = (
    STAGE9_CHAPTER20_MANIFEST,
    STAGE9_CHAPTER15_MANIFEST,
    STAGE9_CHAPTER2_MANIFEST,
)

EVIDENCE_REQUIRED = "evidence_required"
STAGE9_VERIFIED = "stage9_verified"
STAGE9_BLOCKED = "blocked_fail_closed"


@dataclass(frozen=True)
class Stage9TemplateProvenance:
    destination_identity: str
    chapter: int
    stage: int
    dialog_identity: str
    asset_name: str
    template_path: Path
    template_sha256: str
    crop_roi_xyxy: tuple[int, int, int, int]
    source_frame_path: Path
    source_frame_sha256: str
    source_session_id: str
    annotated_source_path: Path
    annotated_source_sha256: str
    runtime_profile: str
    nearby_semantic_label: str
    dialog_source_frame_path: Path | None
    dialog_source_frame_sha256: str
    static_ap_cost: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "destination_identity": self.destination_identity,
            "chapter": self.chapter,
            "stage": self.stage,
            "dialog_identity": self.dialog_identity,
            "asset_name": self.asset_name,
            "template_path": _rel(self.template_path),
            "template_sha256": self.template_sha256,
            "crop_roi_xyxy": list(self.crop_roi_xyxy),
            "source_frame_path": _rel(self.source_frame_path),
            "source_frame_sha256": self.source_frame_sha256,
            "source_session_id": self.source_session_id,
            "annotated_source_path": _rel(self.annotated_source_path),
            "annotated_source_sha256": self.annotated_source_sha256,
            "runtime_profile": self.runtime_profile,
            "nearby_semantic_label": self.nearby_semantic_label,
            "dialog_source_frame_path": (
                _rel(self.dialog_source_frame_path) if self.dialog_source_frame_path else None
            ),
            "dialog_source_frame_sha256": self.dialog_source_frame_sha256,
            "static_ap_cost": self.static_ap_cost,
        }


@dataclass(frozen=True)
class Stage9EvidenceDecision:
    destination: str
    status: str
    transport_count: int
    dispatch_authorized: bool
    evidence_required: bool
    reason: str
    provenance: Stage9TemplateProvenance | None = None
    recognized_stage_identity: str | None = None
    recognized_dialog_identity: str | None = None
    chapter_map_frame_sha256: str | None = None
    dialog_frame_sha256: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "destination": self.destination,
            "status": self.status,
            "transport_count": self.transport_count,
            "dispatch_authorized": self.dispatch_authorized,
            "evidence_required": self.evidence_required,
            "reason": self.reason,
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "recognized_stage_identity": self.recognized_stage_identity,
            "recognized_dialog_identity": self.recognized_dialog_identity,
            "chapter_map_frame_sha256": self.chapter_map_frame_sha256,
            "dialog_frame_sha256": self.dialog_frame_sha256,
        }


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_sha256(value: str, *, label: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{label} must be a 64-hex SHA-256 digest")
    return digest


def load_stage9_ground_truth_catalog(
    *,
    manifest_paths: Sequence[Path] | None = None,
) -> dict[str, Stage9TemplateProvenance]:
    """Load retained Stage-9 ground-truth manifests; absent chapters are omitted."""

    paths = list(manifest_paths) if manifest_paths is not None else list(DEFAULT_STAGE9_MANIFESTS)
    catalog: dict[str, Stage9TemplateProvenance] = {}
    for path in paths:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("kind") != "campaign_stage9_chapter_map_ground_truth":
            raise ValueError(f"{path} is not Stage-9 chapter-map ground truth")
        if payload.get("runtime_profile") != CAMPAIGN_PROFILE_ID:
            raise ValueError(f"{path} runtime profile must be {CAMPAIGN_PROFILE_ID}")
        destination = parse_supported_campaign_story_destination(
            str(payload["destination_identity"])
        )
        templates = payload.get("templates") or []
        if len(templates) != 1:
            raise ValueError(f"{path} must declare exactly one Stage-9 template")
        item = templates[0]
        template_path = REPO_ROOT / str(item["template_path"]).replace("\\", "/")
        source_frame = REPO_ROOT / str(item["source_frame_path"]).replace("\\", "/")
        annotated = REPO_ROOT / str(item["annotated_source_path"]).replace("\\", "/")
        for required in (template_path, source_frame, annotated):
            if not required.is_file():
                raise ValueError(f"Stage-9 ground-truth artifact missing: {required}")
        template_sha = _require_sha256(item["template_sha256"], label="template_sha256")
        source_sha = _require_sha256(item["source_frame_sha256"], label="source_frame_sha256")
        annotated_sha = _require_sha256(
            item["annotated_source_sha256"], label="annotated_source_sha256"
        )
        if _file_sha256(template_path) != template_sha:
            raise ValueError(f"Stage-9 template hash mismatch for {template_path}")
        if _file_sha256(source_frame) != source_sha:
            raise ValueError(f"Stage-9 source frame hash mismatch for {source_frame}")
        if _file_sha256(annotated) != annotated_sha:
            raise ValueError(f"Stage-9 annotated source hash mismatch for {annotated}")
        roi = tuple(int(v) for v in item["crop_roi_xyxy"])
        if len(roi) != 4 or not (0 <= roi[0] < roi[2] <= 800 and 0 <= roi[1] < roi[3] <= 1280):
            raise ValueError(f"{path} crop ROI must be inside native 800x1280 bounds")
        dialog = payload.get("dialog_association") or {}
        dialog_path = None
        dialog_sha = ""
        if dialog.get("source_frame_path"):
            dialog_path = REPO_ROOT / str(dialog["source_frame_path"]).replace("\\", "/")
            if not dialog_path.is_file():
                raise ValueError(f"Stage-9 dialog frame missing: {dialog_path}")
            dialog_sha = _require_sha256(
                dialog.get("source_frame_sha256", ""), label="dialog source_frame_sha256"
            )
            if _file_sha256(dialog_path) != dialog_sha:
                raise ValueError(f"Stage-9 dialog frame hash mismatch for {dialog_path}")
        provenance = Stage9TemplateProvenance(
            destination_identity=destination.identity,
            chapter=destination.story_chapter,
            stage=destination.story_stage,
            dialog_identity=str(payload.get("dialog_identity") or destination.dialog_identity),
            asset_name=str(item["asset_name"]),
            template_path=template_path,
            template_sha256=template_sha,
            crop_roi_xyxy=(roi[0], roi[1], roi[2], roi[3]),
            source_frame_path=source_frame,
            source_frame_sha256=source_sha,
            source_session_id=str(item["source_session_id"]),
            annotated_source_path=annotated,
            annotated_source_sha256=annotated_sha,
            runtime_profile=str(item.get("runtime_profile") or payload["runtime_profile"]),
            nearby_semantic_label=str(item.get("nearby_semantic_label") or "").strip(),
            dialog_source_frame_path=dialog_path,
            dialog_source_frame_sha256=dialog_sha,
            static_ap_cost=(
                int(dialog["static_ap_cost"]) if dialog.get("static_ap_cost") is not None else None
            ),
        )
        if not provenance.nearby_semantic_label:
            raise ValueError(f"{path} requires nearby semantic chapter association")
        catalog[destination.identity] = provenance
    return catalog


def stage9_provenance_for_destination(
    destination: str,
    *,
    catalog: Mapping[str, Stage9TemplateProvenance] | None = None,
) -> Stage9TemplateProvenance | None:
    stage = parse_supported_campaign_story_destination(destination)
    resolved = catalog if catalog is not None else load_stage9_ground_truth_catalog()
    return resolved.get(stage.identity)


def evaluate_stage9_on_retained_native_evidence(
    destination: str,
    *,
    catalog: Mapping[str, Stage9TemplateProvenance] | None = None,
) -> Stage9EvidenceDecision:
    """Production-path Stage-9 check against retained native evidence (zero transport).

    Uses ``recognize_campaign_frame`` on the retained chapter-map and dialog frames. Never
    authorizes dispatch. Missing provenance for a supported destination is evidence_required.
    """

    stage = parse_supported_campaign_story_destination(destination)
    provenance = stage9_provenance_for_destination(stage.identity, catalog=catalog)
    if provenance is None:
        return Stage9EvidenceDecision(
            destination=stage.identity,
            status=EVIDENCE_REQUIRED,
            transport_count=0,
            dispatch_authorized=False,
            evidence_required=True,
            reason=(
                f"Stage-9 native chapter-map ground truth is absent for {stage.identity}; "
                "no input authority"
            ),
        )

    import cv2

    from tasks.campaign_auto_battle_vision import recognize_campaign_frame

    chapter_frame = cv2.imread(str(provenance.source_frame_path), cv2.IMREAD_COLOR)
    if chapter_frame is None:
        return Stage9EvidenceDecision(
            destination=stage.identity,
            status=EVIDENCE_REQUIRED,
            transport_count=0,
            dispatch_authorized=False,
            evidence_required=True,
            reason="Stage-9 chapter-map source frame is unreadable",
            provenance=provenance,
        )
    recognition = recognize_campaign_frame(chapter_frame, stage)
    stage_identity = f"campaign-stage-{stage.identity}"
    bound = next((roi for identity, roi in recognition.targets if identity == stage_identity), None)
    if (
        not recognition.observation.recognized
        or recognition.observation.screen is not CampaignScreen.CHAPTER_MAP
        or recognition.observation.chapter_number != stage.story_chapter
        or 9 not in recognition.observation.visible_stage_numbers
        or bound is None
    ):
        return Stage9EvidenceDecision(
            destination=stage.identity,
            status=STAGE9_BLOCKED,
            transport_count=0,
            dispatch_authorized=False,
            evidence_required=False,
            reason=(
                "retained chapter-map frame did not positively rebind Stage 9 under current "
                f"chapter {stage.story_chapter}"
            ),
            provenance=provenance,
            chapter_map_frame_sha256=recognition.frame_sha256,
        )

    dialog_identity = None
    dialog_hash = None
    if provenance.dialog_source_frame_path is not None:
        dialog_frame = cv2.imread(str(provenance.dialog_source_frame_path), cv2.IMREAD_COLOR)
        if dialog_frame is None:
            return Stage9EvidenceDecision(
                destination=stage.identity,
                status=EVIDENCE_REQUIRED,
                transport_count=0,
                dispatch_authorized=False,
                evidence_required=True,
                reason="Stage-9 dialog association frame is unreadable",
                provenance=provenance,
                recognized_stage_identity=stage_identity,
                chapter_map_frame_sha256=recognition.frame_sha256,
            )
        dialog_recognition = recognize_campaign_frame(dialog_frame, stage)
        dialog_stage = dialog_recognition.observation.stage_dialog
        dialog_identity = None if dialog_stage is None else dialog_stage.dialog_identity
        dialog_hash = dialog_recognition.frame_sha256
        expected_dialog = provenance.dialog_identity
        if (
            not dialog_recognition.observation.recognized
            or dialog_recognition.observation.screen is not CampaignScreen.STAGE_DIALOG
            or dialog_identity != expected_dialog
        ):
            return Stage9EvidenceDecision(
                destination=stage.identity,
                status=STAGE9_BLOCKED,
                transport_count=0,
                dispatch_authorized=False,
                evidence_required=False,
                reason=(
                    "retained dialog frame did not positively associate "
                    f"{expected_dialog} with Stage 9"
                ),
                provenance=provenance,
                recognized_stage_identity=stage_identity,
                recognized_dialog_identity=dialog_identity,
                chapter_map_frame_sha256=recognition.frame_sha256,
                dialog_frame_sha256=dialog_hash,
            )

    return Stage9EvidenceDecision(
        destination=stage.identity,
        status=STAGE9_VERIFIED,
        transport_count=0,
        dispatch_authorized=False,
        evidence_required=False,
        reason=(
            f"Stage 9 rebound on retained native chapter map for {stage.identity} with "
            f"dialog {provenance.dialog_identity}; destination verification only, no AP input"
        ),
        provenance=provenance,
        recognized_stage_identity=stage_identity,
        recognized_dialog_identity=dialog_identity or provenance.dialog_identity,
        chapter_map_frame_sha256=recognition.frame_sha256,
        dialog_frame_sha256=dialog_hash,
    )


def evaluate_all_supported_stage9_destinations(
    *,
    catalog: Mapping[str, Stage9TemplateProvenance] | None = None,
) -> tuple[Stage9EvidenceDecision, ...]:
    resolved = catalog if catalog is not None else load_stage9_ground_truth_catalog()
    return tuple(
        evaluate_stage9_on_retained_native_evidence(destination, catalog=resolved)
        for destination in sorted(SUPPORTED_CAMPAIGN_STORY_DESTINATIONS)
    )
