"""Retained-session fixtures shared by the Enhancement replay and recovery tests."""
from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import flow_delivery_enhancement_bluestacks as delivery
from scripts.flow_delivery_enhancement_bluestacks import _rerun_semantics
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    EnhancementObservation,
)
from tasks.runtime_identity import BLUESTACKS_SERIAL


CATEGORIES = ("gear", "chip", "module")
TRANSITION = ["HOME_CANONICAL", "COMMANDER_INFO_RECOGNIZED", "GEAR_SUCCESSOR_RECONCILED",
              "CHIP_SUCCESSOR_RECONCILED", "MODULE_SUCCESSOR_RECONCILED", "SAFE_TERMINAL_RECOGNIZED"]


class CausalReplayFixture:
    """Mixin for a TestCase: exercise retained-event admission; parser semantics have independent native tests."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.session = Path(self.temporary.name).resolve()
        (self.session / "frames").mkdir()
        self.rows = []
        self.paths = {}
        self.digests = {}
        self.roles = {}
        self.before = {}
        self.after = {}
        self.actions = []
        self.reset = "local-2026-10-29-enhancement-family"
        self.targets = {
            "modal_enhance": (450, 800, 650, 870),
            "baseline_card": (190, 610, 280, 700),
            "quantity_use": (270, 760, 530, 840),
        }
        stages = []
        proofs = []
        clock = 0
        for variant in ("gear", "chip", "module"):
            for role in ("modal", "baseline", "quantity", "current", "successor"):
                marker = len(self.roles) + 1
                image = np.full((1280, 800, 3), marker, dtype=np.uint8)
                ok, encoded = cv2.imencode(".png", image)
                self.assertTrue(ok)
                payload = encoded.tobytes()
                path = self.session / "frames" / f"{variant}-{role}.png"
                path.write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                self.paths[variant, role] = path
                self.digests[variant, role] = digest
                self.roles[digest] = (variant, role)
            for role, identity, target in (
                ("modal", f"open-enhance:{variant}", self.targets["modal_enhance"]),
                ("baseline", f"material-select:{variant}", self.targets["baseline_card"]),
                ("quantity", "quantity-use", self.targets["quantity_use"]),
                ("current", "enhancement-use", (485, 1180, 651, 1245)),
                ("successor", None, None),
            ):
                clock += 2
                self.rows.append({
                    "type": "capture", "path": str(self.paths[variant, role]),
                    "sha256": self.digests[variant, role], "captured_monotonic": clock,
                    "timestamp": self.timestamp(clock),
                })
                if identity is not None:
                    self.rows.append({
                        "type": "dispatch", "source_sha256": self.digests[variant, role],
                        "target_identity": identity, "target_roi": target,
                        "point": ((target[0] + target[2]) // 2, (target[1] + target[3]) // 2),
                        "action_key": f"enhancement:{variant}:{identity}:test",
                        "execute": True, "consequential": False, "action_class": "navigation",
                        "timestamp": self.timestamp(clock + 1),
                    })
            before = self.observation(variant, successor=False)
            after = self.observation(variant, successor=True)
            self.before[variant], self.after[variant] = before, after
            self.actions.append({
                "label": "use-one-star-enhancer", "before_sha256": before.source_frame_sha256,
                "immediate_post_sha256": after.source_frame_sha256,
                "after_sha256": after.source_frame_sha256, "recovery_used": False,
            })
            proofs.append({
                "variant": variant, "status": "completed",
                "runtime_session": str(self.session), "source_frame_sha256": before.source_frame_sha256,
                "resource_affecting_action_key": f"enhancement:{variant}:enhancement-use:test",
                "before_observation": asdict(before), "successor_observation": asdict(after),
            })
            for phase, role in (
                ("select-equipped-enhancement-item-settled-1", "modal"),
                ("open-enhance-panel-settled", "baseline"),
                ("select-exact-one-star-material-settled", "quantity"),
                ("apply-quantity-selection-settled", "current"),
                ("use-one-star-enhancer-immediate-before", "current"),
                ("enhancement-settle-0", "successor"),
            ):
                stages.append({"kind": "recognition", "stage": phase,
                    "recognized": True, "variant": variant,
                    "frame_sha256": self.digests[variant, role]})
        image = np.full((1280, 800, 3), 50, dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        payload = encoded.tobytes()
        home = self.session / "frames" / "home.png"
        home.write_bytes(payload)
        self.home_hash = hashlib.sha256(payload).hexdigest()
        self.rows.append({"type": "capture", "path": str(home),
            "sha256": self.home_hash, "captured_monotonic": clock + 2,
            "timestamp": self.timestamp(clock + 2)})
        stages.append({"kind": "recognition", "stage": "commander-to-home-terminal-settled",
            "recognized": True, "variant": "module", "frame_sha256": self.home_hash})
        self.result = {"variant": "family", "reset_identity": self.reset, "actions": self.actions,
            "enhancement_result": {"reset_identity": self.reset, "stages": stages, "category_results": proofs,
                "terminal_frame_sha256": self.home_hash}}
        self.parser_calls = []

    @staticmethod
    def timestamp(clock):
        return datetime.fromtimestamp(1793282400 + clock, timezone.utc).isoformat()

    def observation(self, variant, *, successor):
        role = "successor" if successor else "current"
        return EnhancementObservation(
            screen_state="COMMANDER_INFO", selected_tab=variant.upper(),
            selected_item_kind=variant.upper(), selected_item_identity=f"{variant}-item",
            item_equipped=not successor, item_level=18,
            target_identity="enhancement-confirm", target_roi=(485, 1180, 651, 1245),
            panel_bounds=(0, 0, 800, 1280), control_class="ENHANCE",
            enhance_control_visible=True, action_mode="ENHANCE",
            material_identity=f"{variant}-material-one-star", material_known=True,
            material_available=True, material_star=1,
            material_quantity=0 if successor else 1, quantity=0 if successor else 1,
            material_inventory_count=9561 if successor else 9562,
            item_exp_current=20 if successor else 10, item_exp_required=260000,
            item_exp_preview=None if successor else 20,
            selection_baseline_frame_sha256=None if successor else self.digests[variant, "baseline"],
            selection_baseline_evidence_ref=None if successor else str(self.paths[variant, "baseline"]),
            material_slot_facts=((0, 4, 0, 2), (1, 1, 0 if successor else 1, 9561 if successor else 9562), (2, 0, 0, 100)),
            game_day_id=self.reset, target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
            source_frame_sha256=self.digests[variant, role],
            evidence_refs=tuple(str(self.paths[variant, name]) for name in (
                ("successor",) if successor else ("current", "modal", "baseline", "quantity"))),
            overlay_state="none", runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
        )

    def commander(self, frame, *, variant, stage, source_frame_sha256, evidence_ref, game_day_id):
        del frame, evidence_ref
        self.assertEqual(game_day_id, self.reset)
        actual_variant, role = self.roles[source_frame_sha256]
        self.assertEqual(actual_variant, variant)
        self.parser_calls.append((variant, role, stage))
        if role == "successor":
            return SimpleNamespace(recognized=stage == "post", observation=self.after[variant])
        expected = "item" if role == "modal" else "material"
        return SimpleNamespace(recognized=stage == expected, observation=None)

    def selection(self, current, *, modal, baseline, quantity, variant, game_day_id):
        self.assertEqual(game_day_id, self.reset)
        for role, capture in (("current", current), ("modal", modal), ("baseline", baseline), ("quantity", quantity)):
            self.assertEqual(capture.path, self.paths[variant, role])
            self.assertEqual(capture.sha256, self.digests[variant, role])
        return SimpleNamespace(recognized=True, observation=self.before[variant],
            diagnostics={"selection_context_targets": self.targets})

    def verify(self):
        (self.session / "events.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8")
        with (
            patch("scripts.enhancement_bluestacks.recognize_commander_stage", self.commander),
            patch("scripts.enhancement_bluestacks.recognize_selection_context", self.selection),
            patch("scripts.enhancement_bluestacks.recognize_home_frame", lambda frame, **kw: SimpleNamespace(recognized=kw["source_frame_sha256"] == self.home_hash)),
        ):
            return _rerun_semantics(self.result, self.session, set(self.roles) | {self.home_hash})


class CausalReplayCase(CausalReplayFixture, unittest.TestCase):
    """Instantiable replay fixture for other modules; defines no tests of its own."""


class CategoryResumeSessions:
    """Mixin for a TestCase: builds retained category sessions from causal replay fixtures."""

    def setUp(self):
        self.cases = []

    def make_session(self, current=CATEGORIES, retained=None):
        case = CausalReplayCase()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.cases.append(case)
        retained = retained or {}
        original_proofs = {proof["variant"]: proof for proof in case.result["enhancement_result"]["category_results"]}
        for proof in original_proofs.values():
            proof["resource_affecting_dispatch_count"] = 1
        rows = []
        for row in case.rows:
            if row["type"] == "capture":
                role = case.roles.get(row["sha256"])
                if role is None or role[0] in current:
                    rows.append(row)
            elif any(str(row.get("action_key", "")).startswith(f"enhancement:{variant}:") for variant in current):
                rows.append(row)
                if row.get("target_identity") == "enhancement-use":
                    rows.append({"type": "dispatch_classification", "action_key": row["action_key"],
                        "resource_affecting": True, "consequential": False})
        image = np.full((1280, 800, 3), 52, dtype=np.uint8)
        png = cv2.imencode(".png", image)[1].tobytes()
        source = case.session / "frames" / "initial-home.png"
        source.write_bytes(png)
        (case.session / "source.png").write_bytes(png)
        initial_hash = hashlib.sha256(png).hexdigest()
        rows.insert(0, {"type": "capture", "path": str(source), "sha256": initial_hash,
            "captured_monotonic": 0, "timestamp": case.timestamp(0)})
        case.rows = rows
        proofs = [copy.deepcopy(retained[variant] if variant in retained else original_proofs[variant])
                  for variant in CATEGORIES if variant in retained or variant in current]
        complete = len(proofs) == 3
        stages = [stage for stage in case.result["enhancement_result"]["stages"]
                  if stage["variant"] in current or stage["stage"] == "commander-to-home-terminal-settled"]
        stages.insert(0, {"kind": "recognition", "stage": "family-startup-home", "recognized": True,
            "variant": next(iter(current), "module"), "frame_sha256": initial_hash})
        route = case.result["enhancement_result"]
        route.update(category_results=proofs, stages=stages, reset_identity=case.reset,
            status="completed" if complete else "blocked", reason="CHIP_MODAL_UNPROVEN",
            source_frame_sha256=initial_hash, resource_affecting_dispatch_count=len(proofs),
            postcondition_verified=complete, terminal_recognized=complete, state_transition=TRANSITION)
        case.result.update(
            flow_id=delivery.FLOW_ID, variant="family", status="completed" if complete else "effect_reconciliation_required",
            serial=BLUESTACKS_SERIAL, native_width=800, native_height=1280,
            production_registration="NOT_REGISTERED", scheduler_enabled=False,
            proof_topology="composite" if retained else "continuous",
            frames=[str(Path(row["path"]).relative_to(case.session)) for row in rows if row["type"] == "capture"],
            events_path="events.jsonl", dispatch_count=len(delivery._dispatch_rows(rows)),
            input_count=len(delivery._dispatch_rows(rows)), resource_affecting_dispatch_count=len(current),
            actions=[copy.deepcopy(action) for action, variant in zip(case.actions, CATEGORIES) if variant in current],
            effect_reconciliation_required=not complete, causal_trace_count=1,
            initial_observation={"frame_sha256": initial_hash, "frame_path": "source.png", "invocation_id": "offline-resume"},
            initial_frame_sha256=initial_hash,
        )
        case.result["causal_trace"] = {
            "trace_count": 1, "read_only": True, "input_authority": False, "flow_id": delivery.FLOW_ID,
            "proof_topology": case.result["proof_topology"], "initial_frame_sha256": initial_hash,
            "transport_count": case.result["dispatch_count"], "resource_affecting_dispatch_count": len(current),
        }
        case.result = json.loads(json.dumps(case.result))
        self.persist(case)
        return case

    @staticmethod
    def persist(case):
        (case.session / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in case.rows), encoding="utf-8")
        (case.session / "flow-delivery-result.json").write_text(json.dumps(case.result), encoding="utf-8")



class CategoryResumeCase(CategoryResumeSessions, unittest.TestCase):
    """Instantiable session builder for other modules; defines no tests of its own."""
