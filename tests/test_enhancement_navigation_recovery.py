from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts import pnsctl
from scripts.flow_delivery_enhancement_bluestacks import (
    FLOW_ID,
    _write_read_only_causal_trace,
    _validate_navigation_only_recovery_source,
)


RESET = "local-2026-10-29-enhancement-family"


def _native_frame(root: Path, name: str, marker: int) -> tuple[str, str]:
    image = np.full((1280, 800, 3), marker, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise AssertionError("native test frame did not encode")
    payload = encoded.tobytes()
    reference = f"frames/{name}.png"
    (root / reference).write_bytes(payload)
    return reference, hashlib.sha256(payload).hexdigest()


def _write_navigation_source(root: Path, *, unknown_target: bool = False, resource: bool = False) -> Path:
    (root / "frames").mkdir(parents=True)
    references: list[str] = []
    hashes: list[str] = []
    for name, marker in (
        ("initial", 1),
        ("portrait-before", 2),
        ("commander", 3),
        ("item-before", 4),
        ("item-post", 5),
        ("open-panel", 6),
    ):
        reference, digest = _native_frame(root, name, marker)
        references.append(reference)
        hashes.append(digest)

    events = [
        {"type": "capture", "path": str(root / references[0]), "sha256": hashes[0]},
        {"type": "capture", "path": str(root / references[1]), "sha256": hashes[1]},
        {
            "type": "dispatch",
            "action_class": "navigation",
            "action_key": "enhancement:gear:commander-profile-portrait:test",
            "consequential": False,
            "execute": True,
            "source_sha256": hashes[1],
            "target_identity": "commander-profile-portrait",
            "target_roi": [4, 40, 84, 123],
            **({"resource_affecting": True} if resource else {}),
        },
        {"type": "capture", "path": str(root / references[2]), "sha256": hashes[2]},
        {"type": "capture", "path": str(root / references[3]), "sha256": hashes[3]},
        {
            "type": "dispatch",
            "action_class": "navigation",
            "action_key": "enhancement:gear:item-select:gear:test",
            "consequential": False,
            "execute": True,
            "source_sha256": hashes[3],
            "target_identity": "unknown-target" if unknown_target else "item-select:gear",
            "target_roi": [50, 510, 133, 625],
            **({"resource_affecting": True} if resource else {}),
        },
        {"type": "capture", "path": str(root / references[4]), "sha256": hashes[4]},
        {"type": "capture", "path": str(root / references[5]), "sha256": hashes[5]},
    ]
    (root / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
    )
    route_stages = [
        {
            "kind": "recognition",
            "stage": "family-startup-home",
            "frame_sha256": hashes[0],
            "recognized": True,
        },
        {
            "kind": "recognition",
            "stage": "home-to-commander-immediate-before",
            "frame_sha256": hashes[1],
            "recognized": True,
        },
        {
            "kind": "dispatch",
            "stage": "dispatch:commander-profile-portrait",
            "frame_sha256": hashes[1],
            "action_key": "enhancement:gear:commander-profile-portrait:test",
            "target_identity": "commander-profile-portrait",
            "resource_affecting": False,
        },
        {
            "kind": "recognition",
            "stage": "home-to-commander-settled",
            "frame_sha256": hashes[2],
            "recognized": True,
        },
        {
            "kind": "recognition",
            "stage": "select-equipped-enhancement-item-immediate-before",
            "frame_sha256": hashes[3],
            "recognized": True,
        },
        {
            "kind": "dispatch",
            "stage": "dispatch:item-select:gear",
            "frame_sha256": hashes[3],
            "action_key": "enhancement:gear:item-select:gear:test",
            "target_identity": "item-select:gear",
            "resource_affecting": False,
        },
        {
            "kind": "recognition",
            "stage": "select-equipped-enhancement-item-immediate-post",
            "frame_sha256": hashes[4],
            "recognized": True,
        },
        {
            "kind": "recognition",
            "stage": "open-enhance-panel-immediate-before",
            "frame_sha256": hashes[5],
            "recognized": False,
            "reason": "COMMANDER_INFO_NOT_RECOGNIZED",
        },
    ]
    route = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "blocked",
        "variant": "family",
        "reset_identity": RESET,
        "reason": "open-enhance:gear immediate-before recognition failed: COMMANDER_INFO_NOT_RECOGNIZED",
        "dispatch_count": 2,
        "resource_affecting_dispatch_count": 0,
        "resource_affecting_action_key": None,
        "resource_affecting_action_keys": [],
        "category_results": [],
        "source_frame_sha256": hashes[0],
        "terminal_recognized": False,
        "terminal_frame_sha256": "",
        "stages": route_stages,
    }
    result = {
        "schema_version": 1,
        "flow_id": FLOW_ID,
        "status": "blocked",
        "variant": "family",
        "frames": references,
        "events_path": "events.jsonl",
        "dispatch_count": 2,
        "input_count": 2,
        "max_inputs": 24,
        "resource_affecting_dispatch_count": 0,
        "effect_reconciliation_required": False,
        "terminal_recognized": False,
        "initial_frame_sha256": hashes[0],
        "initial_observation": {"frame_sha256": hashes[0], "frame_path": references[0]},
        "enhancement_result": route,
    }
    (root / "flow-delivery-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


class EnhancementNavigationRecoverySourceTests(unittest.TestCase):
    def test_real_native_zero_use_ledger_is_admitted(self):
        with tempfile.TemporaryDirectory() as folder:
            source = _write_navigation_source(Path(folder))
            proof = _validate_navigation_only_recovery_source(source, reset_identity=RESET)
        self.assertEqual(proof["dispatch_count"], 2)
        self.assertEqual(proof["resource_affecting_dispatch_count"], 0)

    def test_unknown_dispatch_is_rejected_before_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            source = _write_navigation_source(Path(folder), unknown_target=True)
            with self.assertRaises(pnsctl.OperatorError):
                _validate_navigation_only_recovery_source(source, reset_identity=RESET)

    def test_resource_marked_dispatch_is_rejected_before_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            source = _write_navigation_source(Path(folder), resource=True)
            with self.assertRaises(pnsctl.OperatorError):
                _validate_navigation_only_recovery_source(source, reset_identity=RESET)

    def test_wrong_reset_is_rejected_before_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            source = _write_navigation_source(Path(folder))
            with self.assertRaises(pnsctl.OperatorError):
                _validate_navigation_only_recovery_source(
                    source, reset_identity="local-2026-10-28-enhancement-family"
                )

    def test_navigation_receipt_trace_does_not_claim_use_stages(self):
        with tempfile.TemporaryDirectory() as folder:
            source = _write_navigation_source(Path(folder))
            trace = _write_read_only_causal_trace(
                source,
                result={
                    "navigation_only_recovery": True,
                    "recovery_source_validated": True,
                    "proof_topology": "composite",
                    "status": "blocked",
                    "effect_reconciliation_required": False,
                },
                initial_observation={"frame_sha256": "initial", "invocation_id": "test"},
            )
        self.assertEqual(
            trace["stages"],
            [
                "observation",
                "navigation_only_recovery_source",
                "visible_exit_navigation",
                "terminal_home",
            ],
        )
        self.assertNotIn("quantity_use_selection", trace["stages"])


if __name__ == "__main__":
    unittest.main()
