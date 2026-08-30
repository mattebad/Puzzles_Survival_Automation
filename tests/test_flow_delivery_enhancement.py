from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import scripts.flow_delivery_enhancement_bluestacks as delivery
import scripts.navigation_development_boundary as boundary
from scripts.navigation_development_boundary import (
    DevelopmentInitialObservation,
    DevelopmentSession,
)
from scripts.enhancement_bluestacks import (
    CATEGORY_TAB_BOXES,
    GEAR_RED_STAR_ARMOR_ROI,
    EnhancementIntegratedRoute,
    ORDERED_VARIANTS,
    _FlowBlocked,
    recognize_commander_stage,
    recognize_home_frame,
)
from scripts.flow_delivery_enhancement_bluestacks import (
    FLOW_ID,
    MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY,
    _continuation_reservation,
    _decode_native,
    _initial_observation,
    _load_family_progress,
    _persist_unresolved_dispatch,
    _outer_session,
    _retained_path,
    _reserve,
    run_enhancement_family,
    verify_enhancement_family,
)
from scripts import pnsctl
from tasks.enhancement import (
    BLUESTACKS_NATIVE_TARGET_PROVENANCE,
    BLUESTACKS_RUNTIME_PROFILE_ID,
    ENHANCEMENT_SCREEN,
)
from tasks.gameplay_flow_contracts import load_flow_contract


GEOMETRY = {
    "portrait": (55, 100, 145, 190),
    "header": (260, 40, 510, 75),
    "gear": (110, 130, 170, 170),
    "chip": (220, 130, 280, 170),
    "module": (330, 130, 410, 170),
    "selected": (90, 130, 105, 170),
    "item": (180, 300, 390, 340),
    "equipped": (190, 360, 270, 395),
    "level": (190, 410, 280, 440),
    "material": (180, 750, 420, 790),
    "material_selected": (160, 750, 175, 790),
    "quantity": (180, 825, 320, 860),
    "open": (450, 900, 540, 950),
    "use": (450, 960, 560, 1010),
    "result": (180, 330, 430, 365),
}


def _hit(text: str, key: str) -> dict[str, object]:
    return {"text": text, "bounds": GEOMETRY[key]}


def _native_overview_frame(
    selected: str = "gear", *, ambiguous: bool = False
) -> np.ndarray:
    frame = np.zeros((1280, 800, 3), dtype=np.uint8)
    for variant, (x0, y0, x1, y1) in CATEGORY_TAB_BOXES.items():
        if ambiguous and variant in {"gear", "module"}:
            color = (0, 20, 60)
        elif variant == selected:
            color = (0, 20, 80)
        else:
            color = (0, 20, 10)
        frame[y0:y1, x0:x1] = color
    if selected == "gear":
        x0, y0, x1, y1 = GEAR_RED_STAR_ARMOR_ROI
        frame[y0:y1, x0:x1] = np.random.default_rng(19).integers(
            0, 90, size=(y1 - y0, x1 - x0, 3), dtype=np.uint8
        )
        frame[y0 + 20:y1 - 10, x0 + 12:x1 - 12] = (20, 20, 180)
    return frame


def _native_overview_ocr(
    _frame: np.ndarray,
    _roi,
    *,
    level_bounds: tuple[tuple[str, tuple[int, int, int, int]], ...] = (
        ("+15", (69, 225, 102, 240)),
    ),
    detail: bool = False,
):
    values: list[dict[str, object]] = [
        {"text": "Info", "bounds": (260, 20, 310, 55)},
        {"text": "Gear", "bounds": (52, 70, 130, 102)},
        {"text": "Chip", "bounds": (166, 70, 245, 102)},
        {"text": "Module", "bounds": (280, 70, 360, 102)},
        {"text": "Cube", "bounds": (395, 70, 470, 102)},
        {"text": "Bioenhancer", "bounds": (500, 70, 600, 102)},
    ]
    values.extend(
        {"text": text, "bounds": bounds} for text, bounds in level_bounds
    )
    if detail:
        values.extend(
            [
                {"text": "Item: commander gear 1", "bounds": GEOMETRY["item"]},
                {"text": "Equipped", "bounds": GEOMETRY["equipped"]},
            ]
        )
    return values


def _ocr(frame: np.ndarray, roi):
    marker = int(frame[0, 0, 0])
    x0, y0, x1, y1 = roi
    values: list[dict[str, object]] = []

    def add(text: str, key: str) -> None:
        bounds = GEOMETRY[key]
        if x0 <= bounds[0] < bounds[2] <= x1 and y0 <= bounds[1] < bounds[3] <= y1:
            values.append(_hit(text, key))

    if y1 <= 380 and x1 <= 300 and marker in {1, 11}:
        add("Commander Portrait", "portrait")
    if y1 <= 220:
        add("Commander Info", "header")
    if y0 < 360 and y1 > 80:
        add("Gear", "gear")
        add("Chip", "chip")
        add("Module", "module")
        if marker in {3, 4, 5, 6, 7, 8, 9, 10}:
            add("Selected", "selected")
    if y0 < 820 and y1 > 210:
        add("Item: commander gear 1", "item")
        add("Equipped", "equipped")
        add("Level: 5" if marker >= 7 else "Level: 4", "level")
        if marker >= 7:
            add("Result: commander gear 1", "result")
    if y0 < 1140 and y1 > 620 and marker in {5, 6, 7, 8, 9, 10}:
        add("Gear Material One Star", "material")
        add("Quantity: 1", "quantity")
        if marker >= 6:
            add("Selected", "material_selected")
    if y0 < 1260 and y1 > 760:
        if marker in {2, 3, 4}:
            add("Enhance", "open")
        if marker >= 6:
            add("Use", "use")
    return values


def _write_native_frame(session: Path, name: str, marker: int) -> tuple[str, str]:
    frame = np.full((1280, 800, 3), marker, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", frame)
    assert ok
    reference = f"frames/{name}.png"
    payload = encoded.tobytes()
    (session / reference).write_bytes(payload)
    return reference, hashlib.sha256(payload).hexdigest()


def _observation_payload(
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


def _family_verifier_structure(session: Path) -> dict[str, object]:
    (session / "frames").mkdir(parents=True)
    frames: list[str] = []
    events: list[dict[str, object]] = []
    proofs: list[dict[str, object]] = []
    stages: list[dict[str, object]] = []
    source_hash = ""
    terminal_hash = ""
    for index, variant in enumerate(("gear", "chip", "module")):
        before_ref, before_hash = _write_native_frame(
            session, f"{variant}-before", index * 2 + 1
        )
        after_ref, after_hash = _write_native_frame(
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
                "before_observation": _observation_payload(
                    variant, before_hash, before_ref, level=4, successor=False
                ),
                "successor_observation": _observation_payload(
                    variant, after_hash, after_ref, level=5, successor=True
                ),
            }
        )
    terminal_ref, terminal_hash = _write_native_frame(
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
        "serial": pnsctl.BLUESTACKS_SERIAL,
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


class FakeRuntime:
    execute = True

    def __init__(self, root: Path, markers: list[int]):
        self.session = root
        (root / "frames").mkdir(parents=True)
        self.frames = []
        for index, marker in enumerate(markers):
            frame = np.full((1280, 800, 3), marker, dtype=np.uint8)
            ok, encoded = cv2.imencode(".png", frame)
            assert ok
            path = root / "frames" / f"{index:04d}.png"
            path.write_bytes(encoded.tobytes())
            from scripts.bluestacks_native_runtime import CapturedNativeFrame

            self.frames.append(
                CapturedNativeFrame(
                    frame,
                    encoded.tobytes(),
                    hashlib.sha256(encoded.tobytes()).hexdigest(),
                    float(index),
                    path,
                )
            )
        self.index = 0
        self.events: list[dict[str, object]] = []

    def capture(self, label: str):
        frame = self.frames[self.index]
        self.index += 1
        self.events.append({"type": "capture", "label": label, "sha256": frame.sha256, "path": str(frame.path)})
        return frame

    def tap(self, source, **kwargs):
        self.events.append({"type": "dispatch", "source_sha256": source.sha256, **kwargs})

    def back(self, source, *, action_key, target_identity="android-back", **_kwargs):
        self.events.append(
            {
                "type": "dispatch",
                "source_sha256": source.sha256,
                "action_key": action_key,
                "target_identity": target_identity,
            }
        )

    def reconcile(self, action_key, status, post, reason):
        self.events.append(
            {
                "type": "reconcile",
                "action_key": action_key,
                "status": status,
                "post_sha256": post.sha256,
                "reason": reason,
            }
        )

    def _event(self, kind, payload):
        self.events.append({"type": kind, **payload})


class FakeSession:
    def __init__(self, runtime: FakeRuntime):
        self.runtime = runtime
        self.session_directory = runtime.session
        self.input_count = 0
        self.actions: list[dict[str, object]] = []

    def observe(self, capture, *, label):
        return capture(label)

    def run_action(
        self,
        *,
        action_class,
        label,
        capture,
        dispatch,
        recognize,
        authorize=None,
        settled_successor=None,
        **_kwargs,
    ):
        before = capture(f"{label}-immediate-before")
        if authorize is not None:
            authorize(before)
        self.input_count += 1
        dispatch(before)
        after = capture(f"{label}-immediate-post")
        state = recognize(after)
        if state == "unknown" and settled_successor is not None:
            after = settled_successor()
            state = recognize(after)
        self.actions.append(
            {
                "label": label,
                "action_class": action_class,
                "status": "completed" if state != "unknown" else "unknown",
                "after_sha256": after.sha256,
            }
        )
        return SimpleNamespace(status="completed" if state != "unknown" else "unknown")


class DirectCommanderRouteTests(unittest.TestCase):
    def test_adapter_requires_real_active_session_and_exact_initial_observation(self):
        fabricated = SimpleNamespace(
            owner=f"pnsctl-development-session:{FLOW_ID}",
            is_active=True,
            run_action=lambda **_kwargs: None,
            observe=lambda **_kwargs: None,
        )
        with self.assertRaises(pnsctl.OperatorError):
            _outer_session({"development_session": fabricated})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(boundary, "RUNTIME_INPUT_LOCK_PATH", root / "lock.sqlite3"):
                with DevelopmentSession(
                    owner=f"pnsctl-development-session:{FLOW_ID}",
                    invocation_id="enhancement-bound",
                    session_directory=root / "outer",
                    max_inputs=24,
                ) as session:
                    digest = hashlib.sha256(b"initial").hexdigest()
                    initial = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        invocation_id=session.invocation_id,
                    )
                    session.set_initial_observation(initial)
                    lease = {
                        "development_session": session,
                        "initial_observation": initial,
                        "initial_frame_sha256": digest,
                    }
                    self.assertIs(_outer_session(lease), session)
                    self.assertEqual(_initial_observation(lease, session)["frame_sha256"], digest)
                    mismatched = dict(lease)
                    mismatched["initial_observation"] = DevelopmentInitialObservation(
                        {"frame_sha256": digest},
                        digest,
                        invocation_id=session.invocation_id,
                    )
                    with self.assertRaises(pnsctl.OperatorError):
                        _initial_observation(mismatched, session)

    def test_invalid_session_blocks_before_reservation_or_runtime_connection(self):
        lease = {
            "enhancement_variant": "gear",
            "enhancement_reset_identity": "local-day",
            "max_inputs": 24,
            "development_session": object(),
        }
        with (
            patch.object(delivery, "_ensure_family_reservations") as reserve,
            patch.object(delivery.LocalBlueStacksRuntime, "connect") as connect,
        ):
            with self.assertRaises(pnsctl.OperatorError):
                run_enhancement_family({}, lease, live=True)
        reserve.assert_not_called()
        connect.assert_not_called()

    def test_delayed_commander_entry_settles_after_home_immediate_post(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(
                Path(folder),
                [1, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 8, 9],
            )
            session = FakeSession(runtime)
            with patch(
                "scripts.enhancement_bluestacks.recognize_home_nav",
                return_value=SimpleNamespace(is_home=True),
            ), patch("scripts.enhancement_bluestacks.time.sleep") as sleep:
                result = EnhancementIntegratedRoute(
                    runtime,
                    session=session,
                    variant="gear",
                    reset_identity="local-day",
                    ocr_engine=_ocr,
                ).run()
        self.assertEqual(result["status"], "evidence_required", result)
        self.assertEqual(result["reason"], "SAFE_HOME_RETURN_EVIDENCE_REQUIRED")
        sleep.assert_called_once_with(1.0)
        immediate = [
            stage for stage in result["stages"]
            if stage.get("stage") == "home-to-commander-immediate-post"
        ]
        settled = [
            stage for stage in result["stages"]
            if stage.get("stage") == "home-to-commander-settled"
        ]
        self.assertEqual(len(immediate), 1)
        self.assertFalse(immediate[0]["recognized"])
        self.assertEqual(len(settled), 1)
        self.assertTrue(settled[0]["recognized"])
        self.assertNotEqual(
            immediate[0]["frame_sha256"],
            settled[0]["frame_sha256"],
        )
        self.assertEqual(session.actions[0]["status"], "completed")
        self.assertEqual(session.actions[0]["after_sha256"], settled[0]["frame_sha256"])

    def test_family_startup_commander_module_tab_selects_gear_without_portrait(self):
        def module_selected_startup_ocr(frame, roi):
            values = _ocr(frame, roi)
            if (
                int(frame[0, 0, 0]) == 2
                and roi == (0, 80, 800, 360)
            ):
                values.append(_hit("Selected", "module"))
            return values

        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(Path(folder), [2, 2, 3])
            session = FakeSession(runtime)
            route = EnhancementIntegratedRoute(
                runtime,
                session=session,
                variant="gear",
                variants=ORDERED_VARIANTS,
                reset_identity="local-day",
                ocr_engine=module_selected_startup_ocr,
            )
            original_action = route._action

            def stop_after_gear_category(**kwargs):
                if kwargs["identity"] == "category-select:gear":
                    return original_action(**kwargs)
                raise _FlowBlocked("bounded startup assertion")

            route._action = stop_after_gear_category
            with patch(
                "scripts.enhancement_bluestacks.recognize_home_nav",
                return_value=SimpleNamespace(is_home=True),
            ):
                result = route.run()

        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(session.input_count, 1)
        dispatch_targets = [
            row["target_identity"]
            for row in runtime.events
            if row.get("type") == "dispatch"
        ]
        self.assertEqual(dispatch_targets, ["category-select:gear"])
        self.assertNotIn("commander-profile-portrait", dispatch_targets)
        self.assertEqual(
            [row["stage"] for row in result["stages"][:2]],
            ["family-startup-commander", "commander-source"],
        )

    def test_family_unknown_startup_is_zero_input_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(Path(folder), [0])
            session = FakeSession(runtime)
            with patch(
                "scripts.enhancement_bluestacks.recognize_home_nav",
                return_value=SimpleNamespace(is_home=False),
            ):
                result = EnhancementIntegratedRoute(
                    runtime,
                    session=session,
                    variant="gear",
                    variants=ORDERED_VARIANTS,
                    reset_identity="local-day",
                    ocr_engine=lambda _frame, _roi: [],
                ).run()
        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(result["reason"], "STARTUP_STATE_NOT_RECOGNIZED")
        self.assertEqual(session.input_count, 0)
        self.assertFalse(any(row.get("type") == "dispatch" for row in runtime.events))

    def test_direct_route_retains_successor_and_blocks_unproven_home_return(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(
                Path(folder),
                [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 11, 11],
            )
            session = FakeSession(runtime)
            with patch(
                "scripts.enhancement_bluestacks.recognize_home_nav",
                return_value=SimpleNamespace(is_home=True),
            ):
                result = EnhancementIntegratedRoute(
                    runtime,
                    session=session,
                    variant="gear",
                    reset_identity="local-day",
                    ocr_engine=_ocr,
                ).run()
        self.assertEqual(result["status"], "evidence_required", result)
        self.assertEqual(result["reason"], "SAFE_HOME_RETURN_EVIDENCE_REQUIRED")
        self.assertEqual(result["resource_affecting_dispatch_count"], 1)
        self.assertEqual(result["dispatch_count"], len(session.actions))
        self.assertFalse(result["terminal_recognized"])
        self.assertEqual(result["terminal_state"], "evidence_required")
        self.assertFalse(result.get("postcondition_verified", False))
        self.assertEqual(len(result["category_results"]), 1)
        self.assertEqual(result["category_results"][0]["variant"], "gear")
        self.assertEqual(result["category_results"][0]["status"], "completed")
        terminal_records = [
            stage for stage in result["stages"]
            if stage.get("stage") == "enhancement-terminal"
        ]
        self.assertEqual(len(terminal_records), 1)
        self.assertTrue(terminal_records[0]["recognized"])
        dispatch_targets = [
            row["target_identity"]
            for row in runtime.events
            if row.get("type") == "dispatch"
        ]
        self.assertEqual(dispatch_targets[-1], "enhancement-use")
        self.assertNotIn("android-back", dispatch_targets)

    def test_retained_family_home_requires_safe_return_transition_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(Path(folder), [1])
            session = FakeSession(runtime)
            completed = {
                variant: {
                    "variant": variant,
                    "status": "completed",
                    "resource_affecting_action_key": (
                        f"enhancement:{variant}:enhancement-use:1"
                    ),
                }
                for variant in ORDERED_VARIANTS
            }
            with patch(
                "scripts.enhancement_bluestacks.recognize_home_nav",
                return_value=SimpleNamespace(is_home=True),
            ):
                result = EnhancementIntegratedRoute(
                    runtime,
                    session=session,
                    variant="gear",
                    variants=ORDERED_VARIANTS,
                    completed_categories=completed,
                    reset_identity="local-day",
                    ocr_engine=_ocr,
                ).run()
        self.assertEqual(result["status"], "evidence_required", result)
        self.assertEqual(result["reason"], "SAFE_HOME_RETURN_TRANSITION_PROOF_REQUIRED")
        self.assertEqual(result["variant"], "family")
        self.assertFalse(result["terminal_recognized"])
        self.assertEqual(result["dispatch_count"], 0)
        self.assertEqual(result["resource_affecting_dispatch_count"], 3)
        self.assertEqual(session.input_count, 0)
        self.assertNotIn("postcondition_verified", result)
        self.assertNotIn("state_transition", result)
        self.assertEqual(
            [row["variant"] for row in result["category_results"]],
            list(ORDERED_VARIANTS),
        )

    def test_home_requires_unique_profile_portrait_and_native_home(self):
        frame = np.ones((1280, 800, 3), dtype=np.uint8)
        with patch(
            "scripts.enhancement_bluestacks.recognize_home_nav",
            return_value=SimpleNamespace(is_home=True),
        ):
            missing = recognize_home_frame(frame, ocr_engine=lambda _f, _r: [])
            ambiguous = recognize_home_frame(
                frame,
                ocr_engine=lambda _f, _r: [
                    _hit("Commander Portrait", "portrait"),
                    {"text": "Profile Portrait", "bounds": (150, 100, 230, 190)},
                ],
            )
        self.assertEqual(missing.reason, "PROFILE_PORTRAIT_NOT_UNIQUE")
        self.assertEqual(ambiguous.reason, "PROFILE_PORTRAIT_NOT_UNIQUE")
        self.assertFalse(
            recognize_home_frame(
                np.ones((640, 800, 3), dtype=np.uint8), ocr_engine=_ocr
            ).recognized
        )

    def test_home_binds_profile_from_unique_level_and_vip_markers(self):
        frame = np.ones((1280, 800, 3), dtype=np.uint8)
        with patch(
            "scripts.enhancement_bluestacks.recognize_home_nav",
            return_value=SimpleNamespace(is_home=True),
        ):
            recognized = recognize_home_frame(
                frame,
                ocr_engine=lambda _f, _r: [
                    {"text": "47", "bounds": (14, 73, 40, 90)},
                    {"text": "VIP1O", "bounds": (147, 76, 237, 101)},
                ],
            )
            ambiguous = recognize_home_frame(
                frame,
                ocr_engine=lambda _f, _r: [
                    {"text": "47", "bounds": (14, 73, 40, 90)},
                    {"text": "48", "bounds": (42, 73, 62, 90)},
                    {"text": "VIP1O", "bounds": (147, 76, 237, 101)},
                ],
            )
        self.assertTrue(recognized.recognized)
        self.assertEqual(recognized.portrait_identity, "profile-level-47")
        self.assertEqual(recognized.portrait_target, (0, 48, 65, 115))
        self.assertEqual(ambiguous.reason, "PROFILE_PORTRAIT_NOT_UNIQUE")

    def test_home_binds_textured_portrait_when_vip_ocr_is_missing(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)
        frame[40:123, 4:84] = np.random.default_rng(7).integers(
            0, 256, size=(83, 80, 3), dtype=np.uint8
        )
        no_text = lambda _f, _r: []
        with patch(
            "scripts.enhancement_bluestacks.recognize_home_nav",
            return_value=SimpleNamespace(is_home=True),
        ):
            recognized = recognize_home_frame(frame, ocr_engine=no_text)
            flat = recognize_home_frame(
                np.zeros((1280, 800, 3), dtype=np.uint8),
                ocr_engine=no_text,
            )
        self.assertTrue(recognized.recognized)
        self.assertEqual(recognized.portrait_identity, "profile-visual-fixed")
        self.assertEqual(recognized.portrait_target, (4, 40, 84, 123))
        self.assertEqual(flat.reason, "PROFILE_PORTRAIT_NOT_UNIQUE")

    def test_icon_overview_binds_referenced_gear_red_star_armor(self):
        frame = _native_overview_frame("gear")
        result = recognize_commander_stage(
            frame,
            variant="gear",
            stage="item",
            source_frame_sha256="e" * 64,
            ocr_engine=_native_overview_ocr,
            game_day_id="day",
        )
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.item_identity, "gear-red-star-chest-armor")
        self.assertEqual(result.item_level, 0)
        self.assertEqual(result.item_target, GEAR_RED_STAR_ARMOR_ROI)
        self.assertTrue(result.category_selected)
        self.assertIsNone(result.open_target)

    def test_unmapped_chip_reference_fails_closed(self):
        frame = _native_overview_frame("chip")
        result = recognize_commander_stage(
            frame,
            variant="chip",
            stage="item",
            source_frame_sha256="b" * 64,
            ocr_engine=lambda current, roi: _native_overview_ocr(current, roi),
            game_day_id="day",
        )
        self.assertFalse(result.recognized)
        self.assertEqual(result.reason, "ITEM_IDENTITY_NOT_UNIQUE")

    def test_native_ocr_fallback_binds_selected_gear_without_gear_text(self):
        frame = _native_overview_frame("gear")
        hits = [
            {"text": "Info", "bounds": (468, 11, 545, 65)},
            {"text": "Module", "bounds": (349, 92, 451, 114)},
            {"text": "Cube", "bounds": (508, 92, 576, 114)},
            {"text": "Bioenhancer", "bounds": (620, 95, 752, 112)},
            {"text": "+15", "bounds": (69, 225, 102, 240)},
        ]
        result = recognize_commander_stage(
            frame,
            variant="gear",
            stage="item",
            source_frame_sha256="a" * 64,
            ocr_engine=lambda _frame, _roi: hits,
            game_day_id="day",
        )
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.item_identity, "gear-red-star-chest-armor")
        self.assertEqual(result.category_target, (4, 38, 178, 132))
        self.assertTrue(result.category_selected)

    def test_icon_overview_requires_tab_context_even_with_exact_header(self):
        frame = _native_overview_frame("gear")
        hits = [
            {"text": "Commander Info", "bounds": (260, 40, 510, 75)},
            {"text": "Gear", "bounds": (52, 70, 130, 102)},
            {"text": "+15", "bounds": (69, 225, 102, 240)},
        ]
        result = recognize_commander_stage(
            frame,
            variant="gear",
            stage="item",
            source_frame_sha256="b" * 64,
            ocr_engine=lambda _frame, _roi: hits,
            game_day_id="day",
        )
        self.assertFalse(result.recognized)
        self.assertEqual(result.reason, "ITEM_IDENTITY_NOT_UNIQUE")
        self.assertEqual(result.item_identity, "")
        self.assertIsNone(result.item_target)

    def test_icon_overview_does_not_mask_explicit_identity_evidence(self):
        frame = _native_overview_frame("gear")
        cases = (
            (
                "wrong variant",
                (
                    {"text": "Item: commander chip 1", "bounds": GEOMETRY["item"]},
                ),
                "ITEM_VARIANT_CONFLICT",
            ),
            (
                "malformed",
                (
                    {"text": "Item commander gear 1", "bounds": GEOMETRY["item"]},
                ),
                "ITEM_IDENTITY_NOT_UNIQUE",
            ),
            (
                "non-unique",
                (
                    {"text": "Item: commander gear 1", "bounds": GEOMETRY["item"]},
                    {"text": "Identity: commander gear 2", "bounds": (400, 300, 600, 340)},
                ),
                "ITEM_IDENTITY_NOT_UNIQUE",
            ),
        )
        for label, identity_hits, expected_reason in cases:
            with self.subTest(label=label):
                result = recognize_commander_stage(
                    frame,
                    variant="gear",
                    stage="item",
                    source_frame_sha256="c" * 64,
                    ocr_engine=lambda current, roi, identity_hits=identity_hits: [
                        *_native_overview_ocr(current, roi),
                        *identity_hits,
                    ],
                    game_day_id="day",
                )
                self.assertFalse(result.recognized)
                self.assertEqual(result.reason, expected_reason)
                self.assertNotEqual(result.item_identity, "gear-red-star-chest-armor")
                self.assertIsNone(result.item_target)

    def test_module_selected_requesting_gear_keeps_gear_target_unselected(self):
        frame = _native_overview_frame("module")
        result = recognize_commander_stage(
            frame,
            variant="gear",
            stage="tab",
            source_frame_sha256="f" * 64,
            ocr_engine=_native_overview_ocr,
            game_day_id="day",
        )
        self.assertTrue(result.recognized, result)
        self.assertFalse(result.category_selected)
        self.assertIsNotNone(result.category_target)
        self.assertEqual(result.diagnostics["visual_selected_tab"], "module")

    def test_ambiguous_tab_color_does_not_prove_requested_selection(self):
        frame = _native_overview_frame("gear", ambiguous=True)
        result = recognize_commander_stage(
            frame,
            variant="gear",
            stage="tab",
            source_frame_sha256="0" * 64,
            ocr_engine=_native_overview_ocr,
            game_day_id="day",
        )
        self.assertTrue(result.recognized, result)
        self.assertFalse(result.category_selected)
        self.assertEqual(result.diagnostics["visual_selected_tab"], "")

    def test_gear_reference_absent_or_wrong_color_fails_closed(self):
        absent_frame = _native_overview_frame("gear")
        x0, y0, x1, y1 = GEAR_RED_STAR_ARMOR_ROI
        absent_frame[y0:y1, x0:x1] = 0
        wrong_frame = _native_overview_frame("gear")
        wrong_frame[y0:y1, x0:x1] = (180, 40, 20)
        absent = recognize_commander_stage(
            absent_frame,
            variant="gear",
            stage="item",
            source_frame_sha256="1" * 64,
            ocr_engine=_native_overview_ocr,
            game_day_id="day",
        )
        wrong = recognize_commander_stage(
            wrong_frame,
            variant="gear",
            stage="item",
            source_frame_sha256="2" * 64,
            ocr_engine=_native_overview_ocr,
            game_day_id="day",
        )
        self.assertFalse(absent.recognized)
        self.assertFalse(wrong.recognized)
        self.assertIsNone(absent.item_target)
        self.assertIsNone(wrong.item_target)

    def test_detail_and_material_paths_remain_strict_without_overview_fallback(self):
        frame = _native_overview_frame("gear")
        item = recognize_commander_stage(
            frame,
            variant="gear",
            stage="item",
            source_frame_sha256="3" * 64,
            ocr_engine=lambda current, roi: _native_overview_ocr(
                current, roi, level_bounds=(), detail=True
            ),
            game_day_id="day",
        )
        material = recognize_commander_stage(
            frame,
            variant="gear",
            stage="material",
            source_frame_sha256="4" * 64,
            ocr_engine=lambda current, roi: _native_overview_ocr(
                current, roi, level_bounds=(), detail=True
            ),
            game_day_id="day",
        )
        self.assertFalse(item.recognized)
        self.assertEqual(item.reason, "OPEN_ENHANCE_NOT_RECOGNIZED")
        self.assertFalse(material.recognized)
        self.assertEqual(material.reason, "MATERIAL_IDENTITY_UNKNOWN")
        self.assertNotEqual(item.item_identity, "gear-red-star-chest-armor")

    def test_gear_detail_modal_resumes_directly_at_enhance(self):
        frame = np.zeros((1280, 800, 3), dtype=np.uint8)

        def modal_ocr(_frame, roi):
            if roi == (0, 0, 800, 1280):
                return [{"text": "S.O.F Suit", "bounds": (348, 321, 501, 356)}]
            if roi == (0, 210, 800, 820):
                return [
                    {"text": "+15", "bounds": (344, 415, 385, 440)},
                    {"text": "Basic Stats", "bounds": (334, 607, 485, 630)},
                ]
            if roi == (0, 760, 800, 1260):
                return [
                    {"text": "Promote", "bounds": (278, 938, 377, 975)},
                    {"text": "Replace", "bounds": (424, 953, 518, 977)},
                    {"text": "Unequip", "bounds": (566, 954, 667, 977)},
                ]
            return []

        with patch(
            "scripts.enhancement_bluestacks._classify_selected_category_visual",
            return_value="gear",
        ):
            result = recognize_commander_stage(
                frame,
                variant="gear",
                stage="item",
                source_frame_sha256="7" * 64,
                ocr_engine=modal_ocr,
                game_day_id="day",
            )
        self.assertTrue(result.recognized, result)
        self.assertEqual(result.item_identity, "s.o.f suit")
        self.assertEqual(result.item_level, 15)
        self.assertEqual(result.open_target, (130, 950, 240, 980))

    def test_immediate_before_rebind_blocks_stale_home_without_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(Path(folder), [1, 2])
            session = FakeSession(runtime)
            with patch(
                "scripts.enhancement_bluestacks.recognize_home_nav",
                return_value=SimpleNamespace(is_home=True),
            ):
                result = EnhancementIntegratedRoute(
                    runtime,
                    session=session,
                    variant="gear",
                    reset_identity="local-day",
                    ocr_engine=_ocr,
                ).run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["dispatch_count"], 0)
        self.assertEqual(session.input_count, 0)

    def test_unknown_use_successor_stays_evidence_required_and_reconciles(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(
                Path(folder),
                [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 0],
            )
            session = FakeSession(runtime)
            def unknown_ocr(frame, roi):
                return [] if int(frame[0, 0, 0]) == 0 else _ocr(frame, roi)

            with patch(
                "scripts.enhancement_bluestacks.recognize_home_nav",
                return_value=SimpleNamespace(is_home=True),
            ):
                result = EnhancementIntegratedRoute(
                    runtime,
                    session=session,
                    variant="gear",
                    reset_identity="local-day",
                    ocr_engine=unknown_ocr,
                ).run()
        self.assertEqual(result["status"], "evidence_required", result)
        self.assertEqual(result["resource_affecting_dispatch_count"], 1)
        self.assertTrue(
            any(
                row.get("type") == "reconcile" and row.get("status") == "unresolved"
                for row in runtime.events
            )
        )

    def test_wrong_variant_and_unsafe_material_fail_closed(self):
        frame = np.full((1280, 800, 3), 6, dtype=np.uint8)

        def wrong_variant(_frame, _roi):
            return [
                _hit("Commander Info", "header"),
                _hit("Gear", "gear"),
                _hit("Chip", "chip"),
                _hit("Module", "module"),
                _hit("Selected", "selected"),
                _hit("Item: commander chip 1", "item"),
                _hit("Equipped", "equipped"),
                _hit("Use", "use"),
            ]

        wrong = recognize_commander_stage(
            frame,
            variant="gear",
            stage="item",
            source_frame_sha256="a" * 64,
            ocr_engine=wrong_variant,
            game_day_id="day",
        )
        unsafe = recognize_commander_stage(
            frame,
            variant="gear",
            stage="material",
            source_frame_sha256="b" * 64,
            ocr_engine=lambda _f, _r: [
                *_ocr(np.full((1280, 800, 3), 5, dtype=np.uint8), _r),
                {"text": "Auto Select", "bounds": (500, 800, 590, 840)},
            ],
            game_day_id="day",
        )
        self.assertFalse(wrong.recognized)
        self.assertEqual(wrong.reason, "ITEM_VARIANT_CONFLICT")
        self.assertFalse(unsafe.recognized)


class ContractAndReservationTests(unittest.TestCase):
    def test_completed_ordered_family_verifies_three_uses(self):
        with tempfile.TemporaryDirectory() as folder:
            structure = _family_verifier_structure(Path(folder))
            with patch(
                "scripts.enhancement_bluestacks.recognize_commander_stage",
                return_value=SimpleNamespace(recognized=True),
            ), patch(
                "scripts.enhancement_bluestacks.recognize_home_frame",
                return_value=SimpleNamespace(recognized=True),
            ):
                verified = verify_enhancement_family(structure, {}, {})
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["variant"], "family")
        self.assertEqual(verified["dispatch_count"], 3)
        self.assertTrue(verified["postcondition_verified"])

    def test_completed_family_passes_operational_generic_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            session = root / ".local-captures" / "enhancement-completed"
            _family_verifier_structure(session)
            with (
                patch.object(pnsctl, "REPO_ROOT", root),
                patch.object(
                    pnsctl,
                    "_load_flow_delivery_state",
                    side_effect=pnsctl.OperatorError("no active delivery"),
                ),
                patch(
                    "scripts.enhancement_bluestacks.recognize_commander_stage",
                    return_value=SimpleNamespace(recognized=True),
                ),
                patch(
                    "scripts.enhancement_bluestacks.recognize_home_frame",
                    return_value=SimpleNamespace(recognized=True),
                ),
            ):
                verdict = json.loads(pnsctl.bluestacks_verify_flow(session))
        self.assertEqual(verdict["status"], "verified")
        self.assertEqual(verdict["flow_id"], FLOW_ID)

    def test_empty_stages_cannot_verify_completed_family(self):
        with tempfile.TemporaryDirectory() as folder:
            structure = _family_verifier_structure(Path(folder))
            retained_path = Path(structure["session_directory"]) / "flow-delivery-result.json"
            retained = json.loads(retained_path.read_text(encoding="utf-8"))
            retained["enhancement_result"]["stages"] = []
            retained_path.write_text(
                json.dumps(retained, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            structure["result"]["enhancement_result"]["stages"] = []
            with patch(
                "scripts.enhancement_bluestacks.recognize_commander_stage",
                return_value=SimpleNamespace(recognized=True),
            ), patch(
                "scripts.enhancement_bluestacks.recognize_home_frame",
                return_value=SimpleNamespace(recognized=True),
            ):
                verified = verify_enhancement_family(structure, {}, {})
        self.assertEqual(verified["status"], "evidence_required")
        self.assertEqual(verified["reason"], "independent semantic re-recognition unavailable")

    def test_completed_composite_or_missing_trace_remains_evidence_required(self):
        with tempfile.TemporaryDirectory() as folder:
            structure = _family_verifier_structure(Path(folder))
            retained_path = Path(structure["session_directory"]) / "flow-delivery-result.json"
            original = json.loads(json.dumps(structure["result"]))
            for mutation in (
                {"proof_topology": "composite"},
                {"causal_trace_count": 0, "causal_trace": None},
            ):
                retained = json.loads(json.dumps(original))
                retained.update(mutation)
                retained_path.write_text(
                    json.dumps(retained, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                structure["result"] = retained
                verdict = verify_enhancement_family(structure, {}, {})
                self.assertEqual(verdict["status"], "evidence_required")

    def test_family_runner_and_verifier_reject_stale_single_variant_shape(self):
        dry_run = json.loads(
            run_enhancement_family(
                {},
                {"enhancement_variant": "gear", "max_inputs": 3},
                live=False,
            )
        )
        self.assertEqual(dry_run["variant"], "family")
        with self.assertRaises(pnsctl.OperatorError):
            verify_enhancement_family(
                {
                    "result": {"flow_id": FLOW_ID, "variant": "gear"},
                    "session_directory": "",
                },
                {},
                {},
            )

    def test_contract_has_direct_commander_path_without_daily_proof(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "gameplay_flow_contracts"
            / f"{FLOW_ID}.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(load_flow_contract(FLOW_ID)["schema_version"], 2)
        self.assertEqual(payload["ordered_categories"], list(ORDERED_VARIANTS))
        self.assertEqual(payload["family_constraints"]["maximum_total_uses"], 3)
        serialized = json.dumps(payload).lower()
        self.assertNotIn("daily", serialized)
        self.assertEqual(payload["scenarios"][0]["start_state"], "HOME_CANONICAL")
        self.assertIn("return-canonical-home", [item["transition_id"] for item in payload["transition_contracts"]])

    def test_contract_requires_ordered_family_completion(self):
        payload = load_flow_contract(FLOW_ID)
        self.assertEqual(payload["completion_identity"], "enhancement-family-bluestacks-integration:gear-chip-module-home-complete")
        transitions = payload["scenarios"][0]["required_transitions"]
        self.assertEqual(transitions.count("use-one-enhancer"), 3)
        self.assertEqual(transitions.count("settle-same-item-successor"), 3)

    def test_conflicting_post_result_identities_fail_closed(self):
        frame = np.full((1280, 800, 3), 7, dtype=np.uint8)

        def conflicting(_frame, roi):
            hits = _ocr(frame, roi)
            if roi == (0, 210, 800, 820):
                hits.extend([
                    _hit("Result: commander gear 1", "result"),
                    {"text": "Result: commander chip 1", "bounds": (440, 330, 620, 365)},
                ])
            return hits

        result = recognize_commander_stage(
            frame, variant="gear", stage="post",
            source_frame_sha256="c" * 64, ocr_engine=conflicting,
            game_day_id="day",
        )
        self.assertFalse(result.recognized)
        self.assertIn(result.reason, {"RESULT_IDENTITY_CONFLICT", "ITEM_CATEGORY_CONFLICT"})

    def test_tab_marker_must_bind_to_one_requested_category(self):
        frame = np.ones((1280, 800, 3), dtype=np.uint8)

        def ambiguous(_frame, roi):
            if roi == (0, 80, 800, 360):
                return [
                    _hit("Gear", "gear"), _hit("Chip", "chip"),
                    _hit("Module", "module"),
                    {"text": "Selected", "bounds": (135, 130, 260, 170)},
                ]
            return [_hit("Commander Info", "header")]

        result = recognize_commander_stage(
            frame, variant="gear", stage="tab",
            source_frame_sha256="d" * 64, ocr_engine=ambiguous,
            game_day_id="day",
        )
        self.assertFalse(result.recognized)
        self.assertEqual(result.reason, "CATEGORY_SELECTION_AMBIGUOUS")

    def test_malformed_retained_family_result_is_rejected_before_skip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            retained = root / "retained-gear"
            retained.mkdir(parents=True)
            (retained / "flow-delivery-result.json").mkdir()
            (root / "family-progress.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "family-progress.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "flow_id": FLOW_ID,
                        "categories": {
                            "gear": {
                                "status": "completed",
                                "runtime_session": str(retained),
                                "resource_affecting_action_key": "enhancement:gear:enhancement-use:1",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(pnsctl.OperatorError):
                _load_family_progress(root)

    def test_native_frame_decoder_rejects_arbitrary_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.png"
            path.write_bytes(b"not a native image")
            with self.assertRaises(pnsctl.OperatorError):
                _decode_native(path)

    def test_raw_symlink_reference_is_rejected_before_resolve_deterministically(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "target.png"
            target.write_bytes(b"native")
            link = root / "link.png"
            with patch("pathlib.Path.is_symlink", new=lambda path: path == link):
                with self.assertRaisesRegex(pnsctl.OperatorError, "symlink"):
                    _retained_path(root, "link.png", "frame")

    def test_dispatch_bearing_use_is_persisted_and_blocks_continuation(self):
        with tempfile.TemporaryDirectory() as folder:
            flow_root = Path(folder) / FLOW_ID
            runtime_session = flow_root / "runtime"
            runtime_session.mkdir(parents=True)
            action_key = "enhancement:gear:enhancement-use:1"
            _persist_unresolved_dispatch(
                flow_root,
                runtime_session,
                [
                    {
                        "type": "dispatch",
                        "target_identity": "enhancement-use",
                        "action_key": action_key,
                    }
                ],
                None,
            )
            progress = json.loads(
                (flow_root / "family-progress.json").read_text(encoding="utf-8")
            )
            gear = progress["categories"]["gear"]
            self.assertEqual(gear["status"], "dispatch_bearing_unresolved")
            self.assertEqual(gear["resource_affecting_action_key"], action_key)
            self.assertEqual(gear["runtime_session"], str(runtime_session))
            with self.assertRaisesRegex(pnsctl.OperatorError, "unresolved dispatch-bearing Use"):
                _load_family_progress(flow_root)

    def test_retained_gear_reconciliation_releases_only_capture_only_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            root.mkdir()
            reservation_at = "20260818T171954671861Z"
            reservation = root / "reservation-gear.json"
            reservation.write_text(
                json.dumps(
                    {
                        "dispatch_bearing": True,
                        "flow_id": FLOW_ID,
                        "reserved_at": reservation_at,
                        "status": "reserved",
                        "variant": "gear",
                    }
                ),
                encoding="utf-8",
            )
            run_root = root / f"run-gear-{reservation_at}"
            nested = run_root / "enhancement-gear-20260818T172932057439Z"
            frames = nested / "frames"
            frames.mkdir(parents=True)
            png = np.zeros((1280, 800, 3), dtype=np.uint8)
            ok, encoded = cv2.imencode(".png", png)
            self.assertTrue(ok)
            frame_path = frames / "0001.png"
            frame_path.write_bytes(encoded.tobytes())
            digest = hashlib.sha256(encoded.tobytes()).hexdigest()
            (nested / "events.jsonl").write_text(
                json.dumps(
                    {
                        "type": "capture",
                        "path": str(frame_path),
                        "sha256": digest,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (nested / "result.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "flow_id": FLOW_ID,
                        "status": "blocked",
                        "reason": "CANONICAL_HOME_NOT_RECOGNIZED",
                        "variant": "gear",
                        "reset_identity": "local-day",
                        "source_frame_sha256": digest,
                        "stages": [
                            {
                                "stage": "home-source",
                                "frame_sha256": digest,
                                "recognized": False,
                            }
                        ],
                        "dispatch": False,
                        "dispatch_count": 0,
                        "resource_affecting_dispatch_count": 0,
                        "resource_affecting_action_key": None,
                        "terminal_recognized": False,
                        "terminal_frame_sha256": "",
                        "terminal_state": "evidence_required",
                        "production_registration": "NOT_REGISTERED",
                        "scheduler_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "operator-stdout.log").write_text("", encoding="utf-8")
            (run_root / "operator-stderr.log").write_text(
                "Traceback (most recent call last):\n"
                '  File "C:\\repo\\scripts\\enhancement_bluestacks.py", line 23, in <module>\n'
                "    from scripts.bluestacks_native_runtime import (\n"
                "ModuleNotFoundError: No module named 'scripts'\n",
                encoding="utf-8",
            )
            self.assertTrue(_continuation_reservation(root, "gear"))
            self.assertFalse(reservation.exists())

    def test_dispatch_bearing_retained_evidence_never_releases_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            root.mkdir()
            reservation_at = "20260818T171954671861Z"
            reservation = root / "reservation-gear.json"
            reservation.write_text(
                json.dumps(
                    {
                        "dispatch_bearing": True,
                        "flow_id": FLOW_ID,
                        "reserved_at": reservation_at,
                        "status": "reserved",
                        "variant": "gear",
                    }
                ),
                encoding="utf-8",
            )
            run_root = root / f"run-gear-{reservation_at}"
            nested = run_root / "enhancement-gear-20260818T172932057439Z"
            (nested / "frames").mkdir(parents=True)
            (nested / "events.jsonl").write_text('{"type":"dispatch"}\n', encoding="utf-8")
            (nested / "result.json").write_text("{}", encoding="utf-8")
            (run_root / "operator-stdout.log").write_text("", encoding="utf-8")
            (run_root / "operator-stderr.log").write_text(
                "Traceback (most recent call last):\n"
                '  File "C:\\repo\\scripts\\enhancement_bluestacks.py", line 23, in <module>\n'
                "    from scripts.bluestacks_native_runtime import (\n"
                "ModuleNotFoundError: No module named 'scripts'\n",
                encoding="utf-8",
            )
            with self.assertRaises(pnsctl.OperatorError):
                _continuation_reservation(root, "gear")
            self.assertTrue(reservation.exists())

    def test_reservation_budget_constant_remains_one_per_category(self):
        self.assertEqual(MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY, 1)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            path = _reserve(root, "module")
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
