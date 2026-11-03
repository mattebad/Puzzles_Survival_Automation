"""Retained Enhancement family-session fixtures shared by delivery tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from scripts.flow_delivery_enhancement_bluestacks import FLOW_ID
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    ENHANCEMENT_SCREEN,
)
from tasks.runtime_identity import BLUESTACKS_SERIAL


def write_native_frame(session: Path, name: str, marker: int) -> tuple[str, str]:
    frame = np.full((1280, 800, 3), marker, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", frame)
    assert ok
    reference = f"frames/{name}.png"
    payload = encoded.tobytes()
    (session / reference).write_bytes(payload)
    return reference, hashlib.sha256(payload).hexdigest()


def observation_payload(
    variant: str,
    digest: str,
    reference: str,
    *,
    level: int,
    successor: bool,
) -> dict[str, object]:
    identity = f"commander-{variant}-1"
    return {
        "screen_state": ENHANCEMENT_SCREEN,
        "selected_tab": variant.upper(),
        "selected_item_kind": variant.upper(),
        "selected_item_identity": identity,
        "item_equipped": True,
        "item_level": level,
        "target_identity": "enhancement-confirm",
        "target_roi": [450, 960, 560, 1010],
        "panel_bounds": [0, 0, 800, 1280],
        "control_class": "ENHANCE",
        "enhance_control_visible": True,
        "action_mode": "ENHANCE",
        "material_identity": f"{variant}-material-one-star",
        "material_known": True,
        "material_available": True,
        "material_star": 1,
        "material_quantity": 1,
        "quantity": 1,
        "enhancement_result_visible": successor,
        "result_identity": identity if successor else "",
        "game_day_id": "local-day",
        "target_provenance": BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        "source_frame_sha256": digest,
        "evidence_refs": [reference],
        "overlay_state": "none",
        "runtime_profile_id": BLUESTACKS_RUNTIME_PROFILE_ID,
        "recognized": True,
        "result_spatially_associated": successor,
    }


def family_verifier_structure(session: Path) -> dict[str, object]:
    (session / "frames").mkdir(parents=True)
    frames: list[str] = []
    events: list[dict[str, object]] = []
    proofs: list[dict[str, object]] = []
    stages: list[dict[str, object]] = []
    source_hash = ""
    terminal_hash = ""
    for index, variant in enumerate(("gear", "chip", "module")):
        before_ref, before_hash = write_native_frame(
            session, f"{variant}-before", index * 2 + 1
        )
        after_ref, after_hash = write_native_frame(
            session, f"{variant}-after", index * 2 + 2
        )
        frames.extend((before_ref, after_ref))
        source_hash = source_hash or before_hash
        terminal_hash = after_hash
        action_key = f"enhancement:{variant}:enhancement-use:1"
        stages.extend(
            [
                {
                    "kind": "recognition",
                    "stage": "use-one-star-enhancer-immediate-before",
                    "frame_sha256": before_hash,
                    "recognized": True,
                    "variant": variant,
                },
                {
                    "kind": "recognition",
                    "stage": "enhancement-settle-0",
                    "frame_sha256": after_hash,
                    "recognized": True,
                    "variant": variant,
                },
            ]
        )
        events.extend(
            [
                {"type": "capture", "sha256": before_hash},
                {
                    "type": "dispatch",
                    "action_key": action_key,
                    "target_identity": "enhancement-use",
                    "source_sha256": before_hash,
                },
                {
                    "type": "dispatch_classification",
                    "action_key": action_key,
                    "resource_affecting": True,
                    "consequential": False,
                },
            ]
        )
        proofs.append(
            {
                "variant": variant,
                "status": "completed",
                "resource_affecting_dispatch_count": 1,
                "resource_affecting_action_key": action_key,
                "before_observation": observation_payload(
                    variant, before_hash, before_ref, level=4, successor=False
                ),
                "successor_observation": observation_payload(
                    variant, after_hash, after_ref, level=5, successor=True
                ),
            }
        )
    terminal_ref, terminal_hash = write_native_frame(
        session, "home-terminal", 99
    )
    frames.append(terminal_ref)
    events.append({"type": "capture", "sha256": terminal_hash})
    stages.append(
        {
            "kind": "recognition",
            "stage": "return-home-immediate-post",
            "frame_sha256": terminal_hash,
            "recognized": True,
            "variant": "module",
        }
    )
    route = {
        "status": "completed",
        "postcondition_verified": True,
        "terminal_recognized": True,
        "source_frame_sha256": source_hash,
        "terminal_frame_sha256": terminal_hash,
        "resource_affecting_dispatch_count": 3,
        "category_results": proofs,
        "stages": stages,
        "state_transition": [
            "HOME_CANONICAL",
            "COMMANDER_INFO_RECOGNIZED",
            "GEAR_SUCCESSOR_RECONCILED",
            "CHIP_SUCCESSOR_RECONCILED",
            "MODULE_SUCCESSOR_RECONCILED",
            "SAFE_TERMINAL_RECOGNIZED",
        ],
    }
    trace = {
        "trace_count": 1,
        "read_only": True,
        "input_authority": False,
        "flow_id": FLOW_ID,
        "proof_topology": "continuous",
        "initial_frame_sha256": source_hash,
        "transport_count": 3,
        "resource_affecting_dispatch_count": 3,
    }
    result = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "completed",
        "variant": "family",
        "serial": BLUESTACKS_SERIAL,
        "native_width": 800,
        "native_height": 1280,
        "runtime_owner": "test-owner",
        "terminal_runtime_state": "recognized_home",
        "actions": [
            {
                "action_class": "ordinary_development_resource_affecting_confirmation",
                "path": "home_to_ordered_enhancement_family_to_home",
                "outcome": "completed",
            }
        ],
        "frames": frames,
        "required_artifacts": ["events_path"],
        "events_path": "events.jsonl",
        "dispatch_count": 3,
        "input_count": 3,
        "resource_affecting_dispatch_count": 3,
        "enhancement_result": route,
        "proof_topology": "continuous",
        "initial_observation": {
            "frame_sha256": source_hash,
            "frame_path": frames[0],
            "invocation_id": "enhancement-fixture",
        },
        "initial_frame_sha256": source_hash,
        "causal_trace_count": 1,
        "causal_trace": trace,
        "effect_reconciliation_required": False,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    (session / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events),
        encoding="utf-8",
    )
    (session / "flow-delivery-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "result": result,
        "session_directory": str(session),
        "frames": frames,
    }


def write_reset_occurrence_state(root, reset, *, pending=False):
    retained = root / "retained-runtime"
    structure = family_verifier_structure(retained)
    result = structure["result"]
    categories = {}
    for proof in result["enhancement_result"]["category_results"]:
        proof["before_observation"]["game_day_id"] = reset
        proof["successor_observation"]["game_day_id"] = reset
        if pending and proof["variant"] == "gear":
            proof["status"] = "dispatch_bearing_unresolved"
            proof["successor_observation"] = None
        categories[proof["variant"]] = {**proof, "runtime_session": str(retained)}
    (retained / "flow-delivery-result.json").write_text(json.dumps(result), encoding="utf-8")
    (root / "family-progress.json").write_text(
        json.dumps({"schema_version": 1, "flow_id": FLOW_ID, "categories": categories}),
        encoding="utf-8",
    )
    return categories
