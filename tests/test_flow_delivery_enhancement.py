from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from scripts import pnsctl
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
from tasks.enhancement import (
    BLUESTACKS_RUNTIME_PROFILE_ID,
    ENHANCEMENT_SCREEN,
    EnhancementObservation,
)
from tasks.profile import BLUESTACKS_NATIVE_TARGET_PROVENANCE
from tasks.gameplay_flow_contracts import load_flow_contract
from tests.support.enhancement_family import (
    family_verifier_structure,
    write_native_frame,
    write_reset_occurrence_state as _write_reset_occurrence_state_support,
)
from tests.support.environment import requires_tesseract



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


_FIXTURE_CONFIRM_TARGET = (485, 1180, 651, 1245)
_FIXTURE_SELECTION_TARGETS = {
    "modal_enhance": (450, 800, 650, 870),
    "baseline_card": (190, 610, 280, 700),
    "quantity_use": (270, 760, 530, 840),
}


def _load_family_fixture(session: Path) -> dict[str, object]:
    result = json.loads(
        (session / "flow-delivery-result.json").read_text(encoding="utf-8")
    )
    return {
        "result": result,
        "session_directory": str(session),
        "frames": result["frames"],
    }


def _prepare_family_fixture(
    structure: dict[str, object], reset: str = "local-2026-10-29-enhancement-family",
) -> dict[str, object]:
    """Give shared structural fixtures current native facts and causal events."""
    result = structure["result"]
    session = Path(structure["session_directory"]).resolve()
    route = result["enhancement_result"]
    route["reset_identity"] = reset
    result["reset_identity"] = reset

    marker = 20
    initial_ref, initial_hash = write_native_frame(session, "home-initial", marker)
    marker += 1
    refs = list(result["frames"]) + [initial_ref]
    rows: list[dict[str, object]] = []
    timestamp = datetime.fromisoformat(
        f"{reset[6:16]}T00:00:00+00:00"
    )
    event_number = 0
    capture_number = 0

    def next_timestamp() -> str:
        nonlocal event_number
        event_number += 1
        return (timestamp + timedelta(seconds=event_number)).isoformat()

    def capture(reference: str, digest: str) -> None:
        nonlocal capture_number
        capture_number += 1
        rows.append(
            {
                "type": "capture",
                "path": reference,
                "sha256": digest,
                "captured_monotonic": float(capture_number),
                "timestamp": next_timestamp(),
            }
        )

    def dispatch(
        identity: str, target: tuple[int, int, int, int], digest: str,
        action_key: str,
    ) -> None:
        rows.append(
            {
                "type": "dispatch",
                "target_identity": identity,
                "target_roi": list(target),
                "point": [(target[0] + target[2]) // 2, (target[1] + target[3]) // 2],
                "action_key": action_key,
                "source_sha256": digest,
                "execute": True,
                "consequential": False,
                "action_class": "navigation",
                "timestamp": next_timestamp(),
            }
        )

    capture(initial_ref, initial_hash)
    route_actions: list[dict[str, object]] = []
    for proof in route["category_results"]:
        variant = proof["variant"]
        before = proof["before_observation"]
        after = proof.get("successor_observation")
        before_ref = before["evidence_refs"][0]
        before_hash = before["source_frame_sha256"]
        after_hash = (
            after["source_frame_sha256"] if after
            else next(
                stage["frame_sha256"] for stage in route["stages"]
                if stage["variant"] == variant and stage["stage"] == "enhancement-settle-0"
            )
        )
        after_ref = after["evidence_refs"][0] if after else next(
            reference for reference in result["frames"]
            if _decode_native(_retained_path(session, reference, "fixture successor")) == after_hash
        )
        modal_ref, modal_hash = write_native_frame(session, f"{variant}-modal", marker)
        marker += 1
        baseline_ref, baseline_hash = write_native_frame(session, f"{variant}-baseline", marker)
        marker += 1
        quantity_ref, quantity_hash = write_native_frame(session, f"{variant}-quantity", marker)
        marker += 1
        refs.extend((modal_ref, baseline_ref, quantity_ref))

        before.update(
            {
                "target_identity": "enhancement-confirm",
                "target_roi": list(_FIXTURE_CONFIRM_TARGET),
                "item_equipped": True,
                "item_level": 4,
                "material_quantity": 1,
                "quantity": 1,
                "material_inventory_count": 9562,
                "item_exp_current": 10,
                "item_exp_required": 260000,
                "item_exp_preview": 20,
                "selection_baseline_frame_sha256": baseline_hash,
                "selection_baseline_evidence_ref": baseline_ref,
                "material_slot_facts": [
                    [0, 4, 0, 2], [1, 1, 1, 9562], [2, 0, 0, 100],
                ],
                "game_day_id": reset,
                "source_frame_sha256": before_hash,
                "evidence_refs": [before_ref, modal_ref, baseline_ref, quantity_ref],
                "enhancement_result_visible": False,
                "result_identity": "",
                "result_spatially_associated": False,
                "recognized": True,
            }
        )
        if after is not None:
            after.update(
                {
                    "target_identity": "enhancement-confirm",
                    "target_roi": list(_FIXTURE_CONFIRM_TARGET),
                    "item_equipped": False,
                    "item_level": 4,
                    "material_quantity": 0,
                    "quantity": 0,
                    "material_inventory_count": 9561,
                    "item_exp_current": 20,
                    "item_exp_required": 260000,
                    "item_exp_preview": None,
                    "selection_baseline_frame_sha256": None,
                    "selection_baseline_evidence_ref": None,
                    "material_slot_facts": [
                        [0, 4, 0, 2], [1, 1, 0, 9561], [2, 0, 0, 100],
                    ],
                    "game_day_id": reset,
                    "source_frame_sha256": after_hash,
                    "evidence_refs": [after_ref],
                    "enhancement_result_visible": True,
                    "result_identity": before["selected_item_identity"],
                    "result_spatially_associated": True,
                    "recognized": True,
                }
            )
        proof["runtime_session"] = str(session)
        proof["source_frame_sha256"] = before_hash

        action_key = proof["resource_affecting_action_key"]
        for reference, digest, identity, target in (
            (modal_ref, modal_hash, f"open-enhance:{variant}", _FIXTURE_SELECTION_TARGETS["modal_enhance"]),
            (baseline_ref, baseline_hash, f"material-select:{variant}", _FIXTURE_SELECTION_TARGETS["baseline_card"]),
            (quantity_ref, quantity_hash, "quantity-use", _FIXTURE_SELECTION_TARGETS["quantity_use"]),
            (before_ref, before_hash, "enhancement-use", _FIXTURE_CONFIRM_TARGET),
        ):
            capture(reference, digest)
            key = (
                action_key if identity == "enhancement-use"
                else f"enhancement:{variant}:{identity}:fixture"
            )
            dispatch(identity, target, digest, key)
            if identity == "enhancement-use":
                rows.append(
                    {
                        "type": "dispatch_classification",
                        "action_key": key,
                        "resource_affecting": True,
                        "consequential": False,
                        "timestamp": next_timestamp(),
                    }
                )
        capture(after_ref, after_hash)
        route_actions.append(
            {
                "label": "use-one-star-enhancer",
                "before_sha256": before_hash,
                "immediate_post_sha256": after_hash,
                "after_sha256": after_hash,
                "recovery_used": False,
                "action_key": action_key,
            }
        )

    terminal_hash = route["terminal_frame_sha256"]
    terminal_ref = next(
        reference for reference in result["frames"]
        if _decode_native(_retained_path(session, reference, "fixture terminal")) == terminal_hash
    )
    capture(terminal_ref, terminal_hash)
    route["stages"].insert(
        0,
        {
            "kind": "recognition",
            "stage": "home-source",
            "frame_sha256": initial_hash,
            "recognized": True,
            "variant": "gear",
        },
    )
    result["frames"] = refs
    result["initial_observation"] = {
        "frame_sha256": initial_hash,
        "frame_path": initial_ref,
        "invocation_id": "enhancement-family-fixture",
    }
    result["initial_frame_sha256"] = initial_hash
    result["dispatch_count"] = len([row for row in rows if row["type"] == "dispatch"])
    result["input_count"] = result["dispatch_count"]
    result["resource_affecting_dispatch_count"] = 3
    result["actions"] = route_actions
    result["causal_trace"] = {
        **result["causal_trace"],
        "initial_frame_sha256": initial_hash,
        "transport_count": result["dispatch_count"],
        "resource_affecting_dispatch_count": 3,
    }
    (session / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (session / "flow-delivery-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    structure["frames"] = refs
    return structure


def _write_reset_fixture(root: Path, reset: str, *, pending: bool = False):
    _write_reset_occurrence_state_support(root, reset, pending=pending)
    session = root / "retained-runtime"
    structure = _prepare_family_fixture(_load_family_fixture(session), reset)
    proofs = structure["result"]["enhancement_result"]["category_results"]
    categories = {
        proof["variant"]: {**proof, "runtime_session": str(session.resolve())}
        for proof in proofs
    }
    (root / "family-progress.json").write_text(
        json.dumps(
            {"schema_version": 1, "flow_id": FLOW_ID, "categories": categories},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return categories


@contextmanager
def _family_replay_patches(structure: dict[str, object]):
    result = structure["result"]
    route = result["enhancement_result"]
    proofs = {
        proof["variant"]: (
            delivery._observation(proof["before_observation"], f"{proof['variant']} fixture before"),
            delivery._observation(proof["successor_observation"], f"{proof['variant']} fixture successor"),
        )
        for proof in route["category_results"]
    }
    allowed_home = {
        result["initial_frame_sha256"],
        route["terminal_frame_sha256"],
    }

    def commander(
        _frame, *, variant, stage, source_frame_sha256, **_kwargs,
    ):
        before, after = proofs[variant]
        expected = after if stage == "post" else before
        return SimpleNamespace(
            recognized=expected.source_frame_sha256 == source_frame_sha256,
            observation=expected,
        )

    def selection(
        current, *, variant, game_day_id, **_witnesses,
    ):
        before, _after = proofs[variant]
        valid = (
            current.sha256 == before.source_frame_sha256
            and game_day_id == route["reset_identity"]
        )
        return SimpleNamespace(
            recognized=valid,
            frame_sha256=current.sha256,
            observation=before if valid else None,
            diagnostics={"selection_context_targets": _FIXTURE_SELECTION_TARGETS},
        )

    with (
        patch("scripts.enhancement_bluestacks.recognize_commander_stage", commander),
        patch("scripts.enhancement_bluestacks.recognize_selection_context", selection),
        patch(
            "scripts.enhancement_bluestacks.recognize_home_frame",
            lambda _frame, *, source_frame_sha256, **_kwargs: SimpleNamespace(
                recognized=source_frame_sha256 in allowed_home
            ),
        ),
    ):
        yield


@contextmanager
def _route_replay_patches(reset: str):
    selected: dict[str, object] = {}

    def observation(
        frame, *, after: bool = False, digest: str = "", reference: str = "",
    ) -> EnhancementObservation:
        digest = digest or getattr(frame, "sha256", "")
        reference = reference or str(getattr(frame, "path", ""))
        if not after:
            modal = selected["modal"]
            baseline = selected["baseline"]
            quantity = selected["quantity"]
            references = (
                reference,
                str(modal.path),
                str(baseline.path),
                str(quantity.path),
            )
            return EnhancementObservation(
                screen_state=ENHANCEMENT_SCREEN,
                selected_tab="GEAR",
                selected_item_kind="GEAR",
                selected_item_identity="commander-gear-1",
                item_equipped=True,
                item_level=4,
                target_identity="enhancement-confirm",
                target_roi=_FIXTURE_CONFIRM_TARGET,
                panel_bounds=(0, 0, 800, 1280),
                control_class="ENHANCE",
                enhance_control_visible=True,
                action_mode="ENHANCE",
                material_identity="gear-material-one-star",
                material_known=True,
                material_available=True,
                material_star=1,
                material_quantity=1,
                quantity=1,
                material_inventory_count=9562,
                game_day_id=reset,
                target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
                source_frame_sha256=digest,
                evidence_refs=references,
                overlay_state="none",
                runtime_profile_id=BLUESTACKS_RUNTIME_PROFILE_ID,
                item_exp_current=10,
                item_exp_required=100,
                material_slot_facts=((0, 4, 0, 2), (1, 1, 1, 9562), (2, 0, 0, 100)),
                item_exp_preview=20,
                selection_baseline_frame_sha256=baseline.sha256,
                selection_baseline_evidence_ref=str(baseline.path),
            )
        before = selected["before"]
        return replace(
            before,
            item_equipped=False,
            material_quantity=0,
            quantity=0,
            material_inventory_count=9561,
            enhancement_result_visible=True,
            result_identity=before.selected_item_identity,
            source_frame_sha256=digest,
            evidence_refs=(reference,),
            result_spatially_associated=True,
            item_exp_current=20,
            item_exp_preview=None,
            selection_baseline_frame_sha256=None,
            selection_baseline_evidence_ref=None,
            material_slot_facts=((0, 4, 0, 2), (1, 1, 0, 9561), (2, 0, 0, 100)),
        )

    def marker_of(frame) -> int:
        return int(getattr(frame, "frame", frame)[0, 0, 0])

    def commander(
        frame, *, variant, stage, source_frame_sha256, **_kwargs,
    ):
        marker = marker_of(frame)
        common = {
            "stage": stage,
            "frame_sha256": source_frame_sha256,
            "recognized": variant == "gear",
            "reason": "SYNTHETIC_CAPTURE_WITNESS_RECOGNIZED",
            "category_selected": False,
            "category_target": (50, 70, 140, 110),
            "item_target": (180, 300, 390, 340),
            "open_target": None,
            "detail_state": None,
            "close_target": None,
            "material_target": None,
            "quantity_target": None,
            "quantity": None,
            "material_selected": False,
            "observation": None,
            "diagnostics": {},
        }
        if stage == "tab":
            common["recognized"] = variant == "gear" and marker != 1
            common["category_selected"] = marker >= 3
        elif stage == "item":
            if marker == 3:
                common["category_selected"] = True
            elif marker in {4, 11}:
                common.update(
                    category_selected=True,
                    detail_state="item_modal",
                    open_target=_FIXTURE_SELECTION_TARGETS["modal_enhance"],
                    diagnostics={"footer_controls": {"unequip": (200, 350, 280, 380)}},
                )
                # The final modal is intentionally missing a measured exit.
                common["close_target"] = (
                    (560, 80, 620, 140) if marker == 4 else None
                )
        elif stage == "material":
            if marker == 5:
                common.update(
                    observation=SimpleNamespace(),
                    quantity=0,
                    material_target=_FIXTURE_SELECTION_TARGETS["baseline_card"],
                    diagnostics={"exp_display_state": "committed"},
                )
            elif marker == 6:
                common.update(
                    reason="QUANTITY_ONE_USE_NAVIGATION_RECOGNIZED",
                    quantity=1,
                    material_selected=True,
                    quantity_target=_FIXTURE_SELECTION_TARGETS["quantity_use"],
                )
            else:
                common["recognized"] = False
        elif stage == "post":
            if marker == 0:
                common.update(
                    recognized=False,
                    reason="SUCCESSOR_NOT_RECOGNIZED",
                )
            else:
                common["observation"] = observation(
                    frame,
                    after=True,
                    digest=source_frame_sha256,
                    reference=_kwargs.get("evidence_ref", ""),
                )
        return SimpleNamespace(**common)

    def selection(
        current, *, variant, game_day_id, modal, baseline, quantity, **_kwargs,
    ):
        selected.update(
            modal=modal,
            baseline=baseline,
            quantity=quantity,
        )
        before = observation(current)
        selected["before"] = before
        return SimpleNamespace(
            recognized=variant == "gear" and game_day_id == reset,
            frame_sha256=current.sha256,
            reason="CURRENT_RUN_SELECTION_WITNESSES_RECOGNIZED",
            observation=before,
            material_selected=True,
            quantity=1,
            diagnostics={"selection_context_targets": _FIXTURE_SELECTION_TARGETS},
        )


    def home(frame, *, source_frame_sha256, ocr_engine=None, **_kwargs):
        pixels = getattr(frame, "frame", frame)
        if int(pixels[0, 0, 0]) != 1:
            return SimpleNamespace(
                recognized=False,
                reason="SYNTHETIC_NONHOME_CAPTURE",
                portrait_target=None,
            )
        return recognize_home_frame(
            pixels,
            source_frame_sha256=source_frame_sha256,
            ocr_engine=ocr_engine,
        )

    with (
        patch("scripts.enhancement_bluestacks.recognize_commander_stage", commander),
        patch("scripts.enhancement_bluestacks.recognize_selection_context", selection),
        patch("scripts.enhancement_bluestacks.recognize_home_frame", home),
    ):
        yield


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
        reset = "local-2026-10-29-enhancement-family"
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(
                Path(folder),
                # Retain a fresh modal observation for exit binding after the Use proof.
                [1, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 8, 9, 11, 11],
            )
            session = FakeSession(runtime)
            with (
                _route_replay_patches(reset),
                patch(
                    "scripts.enhancement_bluestacks.is_clean_home_frame",
                    return_value=True,
                ),
                patch("scripts.enhancement_bluestacks.time.sleep"),
            ):
                result = EnhancementIntegratedRoute(
                    runtime,
                    session=session,
                    variant="gear",
                    reset_identity=reset,
                    ocr_engine=_ocr,
                ).run()
        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(result["resource_affecting_dispatch_count"], 1)
        self.assertEqual(session.actions[0]["status"], "completed")
        # Entry commits the fresh settled capture, not its immediate Home result.
        self.assertEqual(session.actions[0]["after_sha256"], runtime.frames[3].sha256)
        self.assertNotEqual(session.actions[0]["after_sha256"], runtime.frames[2].sha256)

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
                "scripts.enhancement_bluestacks.is_clean_home_frame",
                return_value=True,
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
                "scripts.enhancement_bluestacks.is_clean_home_frame",
                return_value=False,
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

    def test_verified_enhancement_keeps_unbound_visible_exit_blocked(self):
        reset = "local-2026-10-29-enhancement-family"
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(
                Path(folder),
                [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 8, 9, 11, 11],
            )
            session = FakeSession(runtime)
            with (
                _route_replay_patches(reset),
                patch(
                    "scripts.enhancement_bluestacks.is_clean_home_frame",
                    return_value=True,
                ),
            ):
                result = EnhancementIntegratedRoute(
                    runtime,
                    session=session,
                    variant="gear",
                    reset_identity=reset,
                    ocr_engine=_ocr,
                ).run()
        self.assertEqual(result["status"], "blocked", result)
        self.assertEqual(result["resource_affecting_dispatch_count"], 1)
        self.assertEqual(result["category_results"][0]["status"], "completed")
        self.assertFalse(result["terminal_recognized"])
        self.assertNotIn("android-back", [
            row["target_identity"]
            for row in runtime.events
            if row.get("type") == "dispatch"
        ])
        dispatch_targets = [
            row["target_identity"]
            for row in runtime.events
            if row.get("type") == "dispatch"
        ]
        self.assertIn("enhancement-use", dispatch_targets)

    def test_retained_family_fresh_home_completes_without_new_input(self):
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
                "scripts.enhancement_bluestacks.is_clean_home_frame",
                return_value=True,
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
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["variant"], "family")
        self.assertTrue(result["terminal_recognized"])
        self.assertEqual(result["dispatch_count"], 0)
        self.assertEqual(result["resource_affecting_dispatch_count"], 3)
        self.assertEqual(session.input_count, 0)
        self.assertTrue(result["postcondition_verified"])
        self.assertTrue(result["state_transition"])
        self.assertEqual(
            [row["variant"] for row in result["category_results"]],
            list(ORDERED_VARIANTS),
        )

    def test_home_requires_unique_profile_portrait_and_native_home(self):
        frame = np.ones((1280, 800, 3), dtype=np.uint8)
        with patch(
            "scripts.enhancement_bluestacks.is_clean_home_frame",
            return_value=True,
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
            "scripts.enhancement_bluestacks.is_clean_home_frame",
            return_value=True,
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
            "scripts.enhancement_bluestacks.is_clean_home_frame",
            return_value=True,
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

    @requires_tesseract
    def test_gear_detail_modal_requires_visible_unique_enhance(self):
        fixture = Path(__file__).parent / "fixtures/enhancement_item_modal/native-gear-sof-suit-20261029.png"
        frame = cv2.imread(str(fixture))
        result = recognize_commander_stage(frame, variant="gear", stage="item")
        self.assertTrue(result.recognized, result)
        self.assertEqual((result.item_identity, result.item_level), ("s.o.f suit", 18))
        button = result.diagnostics["footer_controls"]["enhance"]
        center = ((button[0] + button[2]) // 2, (button[1] + button[3]) // 2)
        self.assertTrue(result.open_target[0] <= center[0] < result.open_target[2])
        self.assertTrue(result.open_target[1] <= center[1] < result.open_target[3])
        missing = frame.copy()
        missing[915:950, 150:260] = 0
        denied = recognize_commander_stage(missing, variant="gear", stage="item")
        self.assertFalse(denied.recognized, denied)
        self.assertIsNone(denied.open_target)

    def test_immediate_before_rebind_blocks_stale_home_without_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(Path(folder), [1, 2])
            session = FakeSession(runtime)
            with patch(
                "scripts.enhancement_bluestacks.is_clean_home_frame",
                return_value=True,
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
        reset = "local-2026-10-29-enhancement-family"
        with tempfile.TemporaryDirectory() as folder:
            runtime = FakeRuntime(
                Path(folder),
                [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 8, 0, 0, 0, 0],
            )
            session = FakeSession(runtime)

            with (
                _route_replay_patches(reset),
                patch(
                    "scripts.enhancement_bluestacks.is_clean_home_frame",
                    return_value=True,
                ),
            ):
                result = EnhancementIntegratedRoute(
                    runtime,
                    session=session,
                    variant="gear",
                    reset_identity=reset,
                    ocr_engine=_ocr,
                ).run()
        self.assertEqual(result["status"], "evidence_required", result)
        self.assertEqual(result["resource_affecting_dispatch_count"], 1)
        self.assertEqual(
            result["category_results"][0]["status"],
            "dispatch_bearing_unresolved",
        )
        self.assertFalse(result["terminal_recognized"])
        dispatch_targets = [
            row["target_identity"]
            for row in runtime.events
            if row.get("type") == "dispatch"
        ]
        self.assertIn("enhancement-use", dispatch_targets)
        self.assertNotIn("android-back", dispatch_targets)
        self.assertTrue(any(
            row.get("type") == "reconcile" and row.get("status") == "unresolved"
            for row in runtime.events
        ))

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
            structure = _prepare_family_fixture(family_verifier_structure(Path(folder)))
            with _family_replay_patches(structure):
                verified = verify_enhancement_family(structure, {}, {})
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["variant"], "family")
        self.assertTrue(verified["postcondition_verified"])
        self.assertEqual(verified["categories_verified"], list(ORDERED_VARIANTS))
        self.assertTrue(verified["causal_trace_verified"])
        self.assertTrue(verified["transport_accounting_verified"])

    def test_completed_family_passes_operational_generic_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            session = root / ".local-captures" / "enhancement-completed"
            structure = _prepare_family_fixture(family_verifier_structure(session))
            with (
                patch.object(pnsctl, "REPO_ROOT", root),
                patch.object(
                    pnsctl,
                    "_load_flow_delivery_state",
                    side_effect=pnsctl.OperatorError("no active delivery"),
                ),
                _family_replay_patches(structure),
            ):
                verdict = json.loads(pnsctl.bluestacks_verify_flow(session))
        self.assertEqual(verdict["status"], "verified")
        self.assertEqual(verdict["flow_id"], FLOW_ID)

    def test_empty_stages_cannot_verify_completed_family(self):
        with tempfile.TemporaryDirectory() as folder:
            structure = _prepare_family_fixture(family_verifier_structure(Path(folder)))
            retained_path = Path(structure["session_directory"]) / "flow-delivery-result.json"
            retained = json.loads(retained_path.read_text(encoding="utf-8"))
            retained["enhancement_result"]["stages"] = []
            retained_path.write_text(
                json.dumps(retained, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            structure["result"]["enhancement_result"]["stages"] = []
            with _family_replay_patches(structure):
                verified = verify_enhancement_family(structure, {}, {})
        self.assertEqual(verified["status"], "evidence_required")
        self.assertFalse(verified.get("postcondition_verified", False))

    def test_completed_composite_or_missing_trace_remains_evidence_required(self):
        with tempfile.TemporaryDirectory() as folder:
            structure = _prepare_family_fixture(family_verifier_structure(Path(folder)))
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


class EnhancementResetOccurrenceTests(unittest.TestCase):
    OLD = "local-2026-10-28-enhancement-family"
    CURRENT = "local-2026-10-29-enhancement-family"

    def test_new_day_has_fresh_occurrence_and_preserves_legacy_and_previous_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            _write_reset_fixture(root, "local-2026-08-18-enhancement-gear")
            prior = root / "occurrences" / self.OLD
            _write_reset_fixture(prior, self.OLD)
            before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            selected, reset, completed = delivery._select_family_state(root, self.CURRENT)
            self.assertEqual(selected, root / "occurrences" / self.CURRENT)
            self.assertEqual(reset, self.CURRENT)
            self.assertEqual(completed, {})
            self.assertFalse(selected.exists())
            reservations = delivery._ensure_family_reservations(selected)
            self.assertEqual(set(reservations), {"gear", "chip", "module"})
            for path, raw in before.items():
                self.assertEqual(path.read_bytes(), raw)

    def test_same_day_returns_only_current_reset_completed_categories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            current = root / "occurrences" / self.CURRENT
            categories = _write_reset_fixture(current, self.CURRENT)
            structure = _load_family_fixture(current / "retained-runtime")
            with _family_replay_patches(structure):
                selected, reset, completed = delivery._select_family_state(root, self.CURRENT)
            self.assertEqual((selected, reset), (current, self.CURRENT))
            self.assertEqual(completed, categories)

    def test_old_proof_cannot_be_adopted_inside_current_occurrence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            current = root / "occurrences" / self.CURRENT
            _write_reset_fixture(current, self.OLD)
            original = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            with self.assertRaises(pnsctl.OperatorError):
                delivery._select_family_state(root, self.CURRENT)
            self.assertTrue(current.exists())
            for path, raw in original.items():
                self.assertEqual(path.read_bytes(), raw)

    def test_legacy_and_prior_unresolved_use_blocks_new_day_without_creating_state(self):
        for legacy in (True, False):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as folder:
                root = Path(folder) / FLOW_ID
                prior = root if legacy else root / "occurrences" / self.OLD
                _write_reset_fixture(prior, self.OLD, pending=True)
                original = (prior / "family-progress.json").read_bytes()
                with self.assertRaisesRegex(pnsctl.OperatorError, "unresolved dispatch-bearing Use"):
                    delivery._select_family_state(root, self.CURRENT)
                self.assertFalse((root / "occurrences" / self.CURRENT).exists())
                self.assertEqual((prior / "family-progress.json").read_bytes(), original)

    def test_pending_recovery_requires_requested_current_reset_category(self):
        for legacy in (True, False):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as folder:
                root = Path(folder) / FLOW_ID
                prior = root if legacy else root / "occurrences" / self.OLD
                _write_reset_fixture(prior, self.OLD, pending=True)
                original = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
                with self.assertRaises(pnsctl.OperatorError):
                    delivery._select_family_state(root, self.CURRENT, recovery_variant="gear")
                self.assertFalse((root / "occurrences" / self.CURRENT).exists())
                self.assertEqual(set(root.rglob("reservation-*.json")), set())
                for path, raw in original.items():
                    self.assertEqual(path.read_bytes(), raw)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            current = root / "occurrences" / self.CURRENT
            _write_reset_fixture(current, self.CURRENT, pending=True)
            original = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            selected, reset, completed = delivery._select_family_state(
                root, self.CURRENT, recovery_variant="gear"
            )
            self.assertEqual((selected, reset, completed), (current, self.CURRENT, {}))
            self.assertEqual(set(root.rglob("reservation-*.json")), set())
            for path, raw in original.items():
                self.assertEqual(path.read_bytes(), raw)

    def test_missing_or_noncurrent_pending_recovery_fails_without_new_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            with self.assertRaises(pnsctl.OperatorError):
                delivery._select_family_state(root, self.CURRENT, recovery_variant="gear")
            self.assertFalse(root.exists())
            _write_reset_fixture(root, self.OLD, pending=True)
            _write_reset_fixture(root / "occurrences" / self.OLD, self.OLD, pending=True)
            original = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            with self.assertRaises(pnsctl.OperatorError):
                delivery._select_family_state(root, self.CURRENT, recovery_variant="gear")
            self.assertFalse((root / "occurrences" / self.CURRENT).exists())
            for path, raw in original.items():
                self.assertEqual(path.read_bytes(), raw)

    def test_malformed_prior_progress_or_reservation_fails_before_new_occurrence(self):
        for filename in ("family-progress.json", "reservation-gear.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as folder:
                root = Path(folder) / FLOW_ID
                prior = root / "occurrences" / self.OLD
                prior.mkdir(parents=True)
                (prior / filename).write_text("{malformed", encoding="utf-8")
                with self.assertRaises(pnsctl.OperatorError):
                    delivery._select_family_state(root, self.CURRENT)
                self.assertFalse((root / "occurrences" / self.CURRENT).exists())

    def test_prior_reservation_without_effect_reconciliation_is_not_discarded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            prior = root / "occurrences" / self.OLD
            delivery._reserve(prior, "gear")
            original = (prior / "reservation-gear.json").read_bytes()
            with self.assertRaisesRegex(pnsctl.OperatorError, "lacks reconciled"):
                delivery._select_family_state(root, self.CURRENT)
            self.assertEqual((prior / "reservation-gear.json").read_bytes(), original)
            self.assertFalse((root / "occurrences" / self.CURRENT).exists())

    def test_reset_rejects_traversal_variant_suffix_and_invalid_calendar_date(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            for reset in ("../escape", "local-2026-10-29-enhancement-gear", "local-2026-02-31-enhancement-family"):
                with self.subTest(reset=reset), self.assertRaises(pnsctl.OperatorError):
                    delivery._select_family_state(root, reset)
            self.assertFalse(root.exists())

    def test_reservation_budget_constant_remains_one_per_category(self):
        self.assertEqual(MAX_DISPATCH_BEARING_CANARY_RUNS_PER_CATEGORY, 1)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / FLOW_ID
            path = _reserve(root, "module")
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
