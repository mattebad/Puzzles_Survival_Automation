#!/usr/bin/env python3
"""Executable, dry-run-by-default local BlueStacks route for Daily troop training."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Mapping

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bluestacks_native_runtime import IntegratedRouteResult, LocalBlueStacksRuntime, NativeRuntimePort
from scripts.home_atlas_bluestacks import (
    BlueStacksLocalizeFirstHomeDriver,
    HomeDriverDisposition,
    ScrcpyMotionEventZoomTransport,
    bluestacks_direct_pan_contract,
)
from scripts.navigation_development_boundary import (
    NavigationBoundaryError,
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    make_source_safety_facts,
)
from tasks.home_atlas import ZoomIdentity, load_home_atlas
from tasks.home_atlas_planner import PlanDisposition, camera_origin
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, BlueStacksHomeLocalizer, bind_visible_building, frame_digest
from tasks.home_context import HomeReadyObservation
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity
from tasks.troop_training import (
    FACILITY_BY_TYPE,
    RESOURCE_NAMES,
    TROOP_TYPES,
    TrainingConfig,
    TrainingController,
    TroopTrainingConfig,
    TrainingScreenObservation,
    default_troop_training_config,
    expected_completion_timestamp,
    make_action_key,
)
from tasks.troop_training_entry import ATLAS_BUILDING_BY_TROOP_TYPE, TroopTrainingAtlasEntryPlanner, first_enabled_entry_target
from tasks.troop_training_runtime import TrainingPhase, TroopTrainingRuntimeController
from tasks.troop_training_vision import (
    QUANTITY_BAND,
    TAB_ROIS,
    forbidden_atlas_entry_surface,
    recognize_auto_use_resource_popup,
    recognize_home,
    recognize_exit_dialog,
    recognize_radial_menu,
    recognize_training_speedup,
    recognize_training,
    recognize_training_with_targets,
)


RESOURCE_BOXES_APPLIED_REAPPLY_TRAINING = "resource boxes applied; reapply exact quantity and authorize a new Train transaction"
DEFAULT_HOME_ATLAS = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
TROOP_TRAINING_FRAME_MAX_AGE_SECONDS = 45.0


def _is_canonical_entry_localization(localization) -> bool:
    return bool(
        localization.recognized
        and localization.zoom_identity is ZoomIdentity.FULLY_ZOOMED_OUT
        and localization.screen_to_atlas is not None
        and not getattr(localization, "stale", False)
        and not getattr(localization, "overlay", False)
    )


def _canonical_home_proof(
    frame: np.ndarray,
    home,
    atlas_path: Path,
    *,
    training=None,
) -> bool:
    """Prove a safe canonical Home surface without requiring four labels.

    Facility OCR is useful for binding a specific building, but it is not a
    stable Home predicate: panning can clip a label at the screen edge.  The
    recovery contract instead requires the native HUD semantic, no recognized
    training/modal surface, and a same-frame fully-zoomed-out Atlas match.
    Non-array frames are accepted only for unit-test doubles that already
    provide a positive Home observation; native runtime frames always take the
    strict HUD/negative-surface path below.
    """

    if training is None:
        training = recognize_training(frame) if isinstance(frame, np.ndarray) else None
    if getattr(training, "recognized", False):
        return False
    if getattr(home, "overlay_state", "none") != "none":
        return False
    diagnostics = getattr(home, "diagnostics", {})
    hud_signal = diagnostics.get("home_hud_signal") if isinstance(diagnostics, Mapping) else None
    if isinstance(frame, np.ndarray):
        # Real HomeObservation instances always expose ``home_hud_signal``.
        # Retain compatibility with existing recognizer test doubles that
        # explicitly report recognized Home but predate that diagnostic key.
        if hud_signal is not True and not (
            getattr(home, "recognized", False)
            and isinstance(diagnostics, Mapping)
            and "home_hud_signal" not in diagnostics
        ):
            return False
        # A Home-looking OCR frame must not be a resource-box/confirmation
        # surface.  This negative gate is bounded to the current native frame.
        if forbidden_atlas_entry_surface(frame) is not None:
            return False
    elif not getattr(home, "recognized", False):
        return False
    if not atlas_path.is_file():
        return False
    try:
        atlas = load_home_atlas(atlas_path)
        localization = BlueStacksHomeLocalizer(atlas, atlas_path).localize(frame)
    except (OSError, ValueError, TypeError):
        return False
    return bool(
        localization.recognized
        and localization.zoom_identity == ZoomIdentity.FULLY_ZOOMED_OUT
    )


@dataclass(frozen=True)
class RadialExteriorCloseBinding:
    target_roi: tuple[int, int, int, int]
    frame_sha256: str
    minimum_building_clearance_px: float
    semantic_evidence: tuple[str, ...]


def bind_radial_exterior_close(frame, localization, atlas, radial, *, troop_type: str) -> RadialExteriorCloseBinding | None:
    """Bind empty current-frame terrain for a safe BlueStacks radial close."""

    if (
        not localization.recognized
        or localization.platform != BLUESTACKS_PLATFORM
        or localization.profile_id != BLUESTACKS_PROFILE_ID
        or localization.screen_to_atlas is None
        or localization.frame_sha256 != frame_digest(frame)
        or radial.facility_identity != FACILITY_BY_TYPE.get(troop_type)
        or not radial.recognized
        or radial.train_target is None
        or radial.overlay_state != "none"
    ):
        return None
    inverse = np.linalg.inv(np.asarray(localization.screen_to_atlas, dtype=np.float64))
    projected_buildings = [
        cv2.perspectiveTransform(np.asarray(building.polygon, dtype=np.float32).reshape(-1, 1, 2), inverse).reshape(-1, 2)
        for building in atlas.buildings
    ]
    safe_region, _ = bluestacks_direct_pan_contract()
    sx0, sy0, sx1, sy1 = safe_region.screen_box
    candidates: list[tuple[float, int, int]] = []
    # Stay away from HUD edges and above the complete radial action row.
    for y in range(max(sy0 + 70, 250), min(sy1, 650) + 1, 25):
        for x in range(max(sx0 + 70, 220), min(sx1 - 70, 575) + 1, 25):
            clearances = []
            occupied = False
            for polygon in projected_buildings:
                signed = float(cv2.pointPolygonTest(polygon, (float(x), float(y)), True))
                if signed >= 0:
                    occupied = True
                    break
                clearances.append(abs(signed))
            if not occupied and clearances and min(clearances) >= 25.0:
                candidates.append((min(clearances), x, y))
    if not candidates:
        return None
    clearance, x, y = max(candidates)
    return RadialExteriorCloseBinding(
        (x - 10, y - 10, x + 10, y + 10),
        localization.frame_sha256,
        clearance,
        (
            f"current-frame facility radial: {radial.facility_identity}",
            "fresh canonical Home atlas localization under known radial",
            "outside every projected semantic building polygon by at least 25 px",
            "inside BlueStacks safe interaction region and above radial controls",
        ),
    )


@dataclass(frozen=True)
class TroopTrainingRouteResult:
    status: str
    reason: str
    actions_completed: int
    completed_claims: tuple[dict[str, object], ...]
    warehouse_approvals: tuple[dict[str, object], ...]
    resource_box_approvals: tuple[dict[str, object], ...]
    training: tuple[dict[str, object], ...]
    daily_progress: dict[str, object]
    final_home_recognized: bool
    entry_navigation: dict[str, object]
    session: str
    resolved_config: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TroopTrainingRecoveryResult:
    status: str
    reason: str
    actions_completed: int
    recovered_action_key: str | None
    troop_type: str | None
    selected_tier: int | None
    quantity: int | None
    displayed_training_duration_seconds: int | None
    expected_completion_timestamp: str | None
    final_home_recognized: bool
    session: str


@dataclass(frozen=True)
class TroopTrainingReturnHomeResult:
    status: str
    reason: str
    actions_completed: int
    final_home_recognized: bool
    session: str


class TroopTrainingReturnHomeRoute:
    """Close a recognized training/radial surface through native navigation only."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        post_input_delay: float = 1.0,
        radial_troop_type: str | None = None,
        atlas_path: Path = DEFAULT_HOME_ATLAS,
        require_active_queue: bool = False,
        allow_queue_empty_training: bool = False,
    ) -> None:
        self.runtime = runtime
        self.post_input_delay = post_input_delay
        self.radial_troop_type = radial_troop_type
        self.atlas_path = atlas_path
        self.require_active_queue = require_active_queue
        self.allow_queue_empty_training = allow_queue_empty_training

    def run(self) -> TroopTrainingReturnHomeResult:
        source = self.runtime.capture("return-home-source")
        recovered_speedup = False
        if recognize_training_speedup(source.frame):
            self.runtime.press_key(
                source,
                key="BACK",
                action_key=f"training:navigation:return-home-speedup-back:{source.sha256}",
            )
            recovered_speedup = True
            time.sleep(self.post_input_delay)
            source = self.runtime.capture("return-home-after-speedup-back")
            recovered_home = recognize_home(source.frame, reset_identity="return-home")
            if _canonical_home_proof(source.frame, recovered_home, self.atlas_path):
                return TroopTrainingReturnHomeResult(
                    "completed",
                    "Training Speedup closed with Back and canonical Home positively localized",
                    1,
                    True,
                    str(self.runtime.session),
                )
        exit_dialog, cancel_target = recognize_exit_dialog(source.frame)
        if exit_dialog and cancel_target is not None:
            if self.require_active_queue:
                # Recovery is authorized only from a fresh, exact queue
                # successor.  An exit dialog obscures that proof; do not tap
                # Cancel and then infer Home from a generic recognizer.
                training = recognize_training(source.frame)
                if not (
                    training.recognized
                    and training.queue_active
                    and training.queue_label
                    and training.queue_troop_type is not None
                    and isinstance(training.queue_tier, int)
                    and isinstance(training.queue_quantity, int)
                    and training.queue_quantity > 0
                    and isinstance(training.training_duration_seconds, int)
                    and training.training_duration_seconds > 0
                    and training.diagnostics.get("duration_source") == "queue_band"
                    and training.diagnostics.get("queue_spatially_associated") is True
                ):
                    return TroopTrainingReturnHomeResult(
                        "blocked",
                        "recovery exit dialog obscures the exact active queue; no input dispatched",
                        0,
                        False,
                        str(self.runtime.session),
                    )
            self.runtime.tap(
                source,
                target_identity="exit-dialog-cancel",
                target_roi=cancel_target,
                action_key=f"training:navigation:exit-dialog-cancel:{source.sha256}",
            )
            time.sleep(self.post_input_delay)
            final = self.runtime.capture("return-home-final-after-cancel")
            if self.require_active_queue:
                final_home = recognize_home(final.frame, reset_identity="return-home")
                final_training = recognize_training(final.frame)
                if not _canonical_home_proof(
                    final.frame,
                    final_home,
                    self.atlas_path,
                    training=final_training,
                ):
                    return TroopTrainingReturnHomeResult(
                        "blocked",
                        "recovery exit dialog canceled without canonical Home Atlas proof",
                        1,
                        False,
                        str(self.runtime.session),
                    )
                return TroopTrainingReturnHomeResult(
                    "completed",
                    "recovery exit dialog canceled and canonical Home Atlas positively localized",
                    1,
                    True,
                    str(self.runtime.session),
                )
            if self.radial_troop_type is not None:
                remaining_radial = recognize_radial_menu(final.frame, troop_type=self.radial_troop_type)
                if remaining_radial.recognized and remaining_radial.train_target is not None:
                    return TroopTrainingReturnHomeResult("blocked", "exit dialog canceled safely; facility radial remains open", 1, False, str(self.runtime.session))
                if forbidden_atlas_entry_surface(final.frame) is not None:
                    return TroopTrainingReturnHomeResult("blocked", "exit dialog canceled but a forbidden or modal surface remains", 1, False, str(self.runtime.session))
                atlas = load_home_atlas(self.atlas_path)
                final_localization = BlueStacksHomeLocalizer(atlas, self.atlas_path).localize(final.frame)
                if not final_localization.recognized:
                    return TroopTrainingReturnHomeResult("blocked", "exit dialog canceled but canonical Home was not localized", 1, False, str(self.runtime.session))
                return TroopTrainingReturnHomeResult("completed", "exit dialog canceled and canonical Home positively localized", 1, True, str(self.runtime.session))
            final_home = recognize_home(final.frame, reset_identity="return-home")
            for attempt in range(2):
                if final_home.recognized:
                    break
                time.sleep(self.post_input_delay)
                final = self.runtime.capture(f"return-home-final-after-cancel-retry-{attempt + 1}")
                final_home = recognize_home(final.frame, reset_identity="return-home")
            if not final_home.recognized:
                return TroopTrainingReturnHomeResult("blocked", "exit dialog canceled but Home/Base was not positively recognized", 1, False, str(self.runtime.session))
            return TroopTrainingReturnHomeResult("completed", "exit dialog canceled and Home/Base positively recognized", 1, True, str(self.runtime.session))
        if self.radial_troop_type is not None:
            radial = recognize_radial_menu(source.frame, troop_type=self.radial_troop_type)
            expected = FACILITY_BY_TYPE[self.radial_troop_type]
            if radial.recognized and radial.facility_identity == expected and radial.train_target is not None and radial.overlay_state == "none":
                fresh = self.runtime.capture("return-home-radial-fresh-before-toggle-close")
                fresh_radial = recognize_radial_menu(fresh.frame, troop_type=self.radial_troop_type)
                if not (
                    fresh_radial.recognized
                    and fresh_radial.facility_identity == expected
                    and fresh_radial.train_target is not None
                    and fresh_radial.overlay_state == "none"
                ):
                    return TroopTrainingReturnHomeResult("blocked", "radial could not be freshly rebound before toggle close", 0, False, str(self.runtime.session))
                localizer = BlueStacksHomeLocalizer(load_home_atlas(self.atlas_path), self.atlas_path)
                self.runtime.press_key(
                    fresh,
                    key="BACK",
                    action_key=f"training:navigation:return-home-radial-back:{self.radial_troop_type}:{fresh.sha256}",
                )
                time.sleep(self.post_input_delay)
                final = self.runtime.capture("return-home-radial-final")
                remaining_radial = recognize_radial_menu(final.frame, troop_type=self.radial_troop_type)
                if remaining_radial.recognized and remaining_radial.train_target is not None:
                    return TroopTrainingReturnHomeResult("blocked", "Back did not close the recognized radial", 1 + int(recovered_speedup), False, str(self.runtime.session))
                if forbidden_atlas_entry_surface(final.frame) is not None:
                    return TroopTrainingReturnHomeResult("blocked", "radial Back reached a forbidden or modal surface", 1 + int(recovered_speedup), False, str(self.runtime.session))
                final_localization = localizer.localize(final.frame)
                if not final_localization.recognized:
                    return TroopTrainingReturnHomeResult("blocked", "radial Back did not prove canonical Home", 1 + int(recovered_speedup), False, str(self.runtime.session))
                return TroopTrainingReturnHomeResult("completed", "recognized radial closed with Back and canonical Home positively localized", 1 + int(recovered_speedup), True, str(self.runtime.session))
        home = recognize_home(source.frame, reset_identity="return-home")
        training = recognize_training(source.frame)
        if self.require_active_queue and not training.recognized:
            # Recovery can begin after the runtime has already returned to
            # canonical Home.  Facility labels may be clipped by the current
            # camera position, so use the bounded HUD + Atlas proof instead of
            # requiring all four OCR labels before returning zero-input.
            if not _canonical_home_proof(
                source.frame,
                home,
                self.atlas_path,
                training=training,
            ):
                return TroopTrainingReturnHomeResult(
                    "blocked",
                    "already-Home recovery lacks canonical Home Atlas proof",
                    0,
                    False,
                    str(self.runtime.session),
                )
            return TroopTrainingReturnHomeResult(
                "completed",
                "already at canonical Home Atlas; no recovery input required",
                0,
                True,
                str(self.runtime.session),
            )
        queue_identity_valid = bool(
            training.recognized
            and training.queue_active
            and training.queue_label
            and training.queue_troop_type is not None
            and isinstance(training.queue_tier, int)
            and isinstance(training.queue_quantity, int)
            and training.queue_quantity > 0
            and isinstance(training.training_duration_seconds, int)
            and training.training_duration_seconds > 0
            and training.diagnostics.get("duration_source") == "queue_band"
            and training.diagnostics.get("queue_spatially_associated") is True
        )
        queue_empty_training_valid = bool(
            self.allow_queue_empty_training
            and training.recognized
            and not training.queue_active
            and not training.queue_label
            and training.overlay_state == "none"
            and isinstance(training.training_duration_seconds, int)
            and training.training_duration_seconds > 0
            and training.diagnostics.get("duration_source") == "normal_train_band"
        )
        if self.require_active_queue and not (queue_identity_valid or queue_empty_training_valid):
            return TroopTrainingReturnHomeResult(
                "blocked",
                "fresh current frame did not positively recognize an exact queue or queue-empty training screen for recovery",
                0,
                False,
                str(self.runtime.session),
            )
        if not home.recognized and not training:
            return TroopTrainingReturnHomeResult("blocked", "current surface is not positively recognized", 0, False, str(self.runtime.session))
        if home.recognized and not training.recognized:
            return TroopTrainingReturnHomeResult("completed", "already at recognized Home/Base", 0, True, str(self.runtime.session))
        # OCR can consume enough time to age the source frame. Rebind the navigation action on a
        # fresh frame and refuse to Back from a radial overlay or any other unknown surface.
        fresh = self.runtime.capture("return-home-fresh-before-back")
        fresh_training = recognize_training(fresh.frame)
        fresh_home = None
        if not fresh_training.recognized:
            fresh_home = recognize_home(fresh.frame, reset_identity="return-home")
        fresh_queue_identity_valid = bool(
            fresh_training.recognized
            and fresh_training.queue_active
            and fresh_training.queue_label
            and fresh_training.queue_troop_type == training.queue_troop_type
            and fresh_training.queue_tier == training.queue_tier
            and fresh_training.queue_quantity == training.queue_quantity
            and fresh_training.training_duration_seconds is not None
            and fresh_training.training_duration_seconds > 0
            and fresh_training.diagnostics.get("duration_source") == "queue_band"
            and fresh_training.diagnostics.get("queue_spatially_associated") is True
        )
        fresh_queue_empty_valid = bool(
            self.allow_queue_empty_training
            and fresh_training.recognized
            and not fresh_training.queue_active
            and not fresh_training.queue_label
            and fresh_training.overlay_state == "none"
            and fresh_training.training_duration_seconds is not None
            and fresh_training.training_duration_seconds > 0
            and fresh_training.diagnostics.get("duration_source") == "normal_train_band"
        )
        if not fresh_training.recognized and self.require_active_queue:
            if _canonical_home_proof(
                fresh.frame,
                fresh_home,
                self.atlas_path,
                training=fresh_training,
            ):
                return TroopTrainingReturnHomeResult("completed", "fresh frame is already at canonical Home Atlas", 0, True, str(self.runtime.session))
            return TroopTrainingReturnHomeResult("blocked", "fresh Home frame lacks canonical Atlas proof", 0, False, str(self.runtime.session))
        if self.require_active_queue and not (fresh_queue_identity_valid or fresh_queue_empty_valid):
            return TroopTrainingReturnHomeResult(
                "blocked",
                "fresh recovery frame did not preserve the exact queue or queue-empty training identity",
                0,
                False,
                str(self.runtime.session),
            )
        if fresh_home is not None and fresh_home.recognized and not fresh_training.recognized:
            return TroopTrainingReturnHomeResult("completed", "fresh frame is already at recognized Home/Base", 0, True, str(self.runtime.session))
        if not fresh_training.recognized:
            return TroopTrainingReturnHomeResult("blocked", "fresh frame is not a recognized training surface; no Back dispatched", 0, False, str(self.runtime.session))
        self.runtime.back(fresh, action_key=f"training:navigation:return-home-only:{fresh.sha256}")
        time.sleep(self.post_input_delay)
        final = self.runtime.capture("return-home-final")
        final_home = recognize_home(final.frame, reset_identity="return-home")
        final_training = recognize_training(final.frame) if isinstance(final.frame, np.ndarray) else None
        if self.require_active_queue and not _canonical_home_proof(
            final.frame,
            final_home,
            self.atlas_path,
            training=final_training,
        ):
            return TroopTrainingReturnHomeResult(
                "blocked",
                "native navigation did not prove canonical Home Atlas localization",
                1,
                False,
                str(self.runtime.session),
            )
        if not final_home.recognized and not self.require_active_queue:
            return TroopTrainingReturnHomeResult("blocked", "native navigation did not prove Home/Base", 1, False, str(self.runtime.session))
        if not self.require_active_queue:
            atlas = load_home_atlas(self.atlas_path)
            terminal_localization = BlueStacksHomeLocalizer(atlas, self.atlas_path).localize(final.frame)
            if not terminal_localization.recognized or terminal_localization.zoom_identity != ZoomIdentity.FULLY_ZOOMED_OUT:
                return TroopTrainingReturnHomeResult(
                    "blocked",
                    "native navigation did not prove canonical Home Atlas localization",
                    1,
                    False,
                    str(self.runtime.session),
                )
        return TroopTrainingReturnHomeResult("completed", "recognized surface closed and Home/Base positively recognized", 1, True, str(self.runtime.session))


class TroopTrainingUnresolvedRecoveryRoute:
    """Reconcile one prior unresolved Train from a fresh native queue frame."""

    def __init__(self, runtime: NativeRuntimePort, *, previous_session: Path, post_input_delay: float = 1.0) -> None:
        self.runtime = runtime
        self.previous_session = previous_session
        self.post_input_delay = post_input_delay

    def _result(self, status: str, reason: str, **values: object) -> TroopTrainingRecoveryResult:
        defaults: dict[str, object] = {
            "actions_completed": 0,
            "recovered_action_key": None,
            "troop_type": None,
            "selected_tier": None,
            "quantity": None,
            "displayed_training_duration_seconds": None,
            "expected_completion_timestamp": None,
            "final_home_recognized": False,
        }
        defaults.update(values)
        return TroopTrainingRecoveryResult(
            status=status,
            reason=reason,
            session=str(self.runtime.session),
            **defaults,
        )

    def _prior_action(self) -> tuple[dict[str, object], dict[str, object]]:
        events_path = self.previous_session / "events.jsonl"
        if not events_path.is_file():
            raise RuntimeError("prior unresolved session events are missing")
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        unresolved = next(
            (
                event
                for event in reversed(events)
                if event.get("type") == "reconcile" and event.get("status") == "unresolved"
            ),
            None,
        )
        if unresolved is None:
            raise RuntimeError("prior session has no unresolved consequential reconciliation")
        action_key = str(unresolved.get("action_key", ""))
        dispatch = next(
            (
                event
                for event in reversed(events)
                if event.get("type") == "dispatch"
                and event.get("consequential")
                and event.get("action_key") == action_key
            ),
            None,
        )
        if dispatch is None or not str(dispatch.get("target_identity", "")).startswith("normal-train:"):
            raise RuntimeError("prior unresolved action is not a normal troop Train dispatch")
        post_path = Path(str(unresolved.get("post_path", "")))
        if not post_path.is_absolute():
            post_path = Path.cwd() / post_path
        if not post_path.is_file():
            raise RuntimeError("prior unresolved immediate-post evidence is missing")
        return dispatch, {**unresolved, "post_path": str(post_path)}

    def run(self) -> TroopTrainingRecoveryResult:
        try:
            dispatch, unresolved = self._prior_action()
            old_post_path = Path(str(unresolved["post_path"]))
            old_frame = cv2.imread(str(old_post_path), cv2.IMREAD_COLOR)
            if old_frame is None:
                return self._result("blocked", "prior immediate-post frame could not be read")
            old_observation = recognize_training(old_frame)
            if not old_observation.recognized or not old_observation.queue_active:
                return self._result("blocked", "prior immediate-post frame does not positively prove an active queue")
            troop_type = old_observation.troop_type
            if (
                troop_type is None
                or old_observation.selected_tier is None
                or old_observation.selected_quantity is None
                or old_observation.training_duration_seconds is None
            ):
                return self._result("blocked", "prior queue identity is incomplete")
            dispatched_at = datetime.fromisoformat(str(dispatch["timestamp"]))
            expected = expected_completion_timestamp(dispatched_at, old_observation.training_duration_seconds)

            current = self.runtime.capture("unresolved-recovery-current-training")
            current_observation = recognize_training(current.frame)
            if not current_observation.recognized or not current_observation.queue_active:
                return self._result(
                    "blocked",
                    "fresh frame does not positively prove an active queue",
                    recovered_action_key=str(dispatch["action_key"]),
                    troop_type=troop_type,
                )
            if (
                current_observation.troop_type != troop_type
                or current_observation.selected_tier != old_observation.selected_tier
                or current_observation.selected_quantity != old_observation.selected_quantity
                or current_observation.training_duration_seconds is None
            ):
                return self._result(
                    "blocked",
                    "fresh queue identity does not match the prior unresolved action",
                    recovered_action_key=str(dispatch["action_key"]),
                    troop_type=troop_type,
                )
            self.runtime.record_recovery(
                action_key=str(dispatch["action_key"]),
                previous_session=str(self.previous_session),
                previous_source_sha256=str(dispatch["source_sha256"]),
                previous_post_sha256=str(unresolved["post_sha256"]),
                current=current,
                expected_completion_timestamp=expected.isoformat(),
                reason="fresh native queue matches prior unresolved Train by troop type, tier, quantity, and timer",
            )
            self.runtime.back(current, action_key=f"training:recovery:return-home:{current.sha256}")
            time.sleep(self.post_input_delay)
            final = self.runtime.capture("unresolved-recovery-final-home")
            final_home = recognize_home(final.frame, reset_identity="recovery")
            values = {
                "recovered_action_key": str(dispatch["action_key"]),
                "troop_type": troop_type,
                "selected_tier": old_observation.selected_tier,
                "quantity": old_observation.selected_quantity,
                "displayed_training_duration_seconds": old_observation.training_duration_seconds,
                "expected_completion_timestamp": expected.isoformat(),
                "final_home_recognized": final_home.recognized,
                "actions_completed": 1,
            }
            if not final_home.recognized:
                return self._result("blocked", "recovery navigation did not positively return Home/Base", **values)
            return self._result(
                "completed",
                "prior unresolved Train reconciled from a fresh active queue and returned Home/Base",
                **values,
            )
        except Exception as exc:
            return self._result("blocked", f"safe recovery stop: {exc}")


class TroopTrainingForbiddenPopupRecoveryRoute(TroopTrainingUnresolvedRecoveryRoute):
    """Cancel one exact forbidden Auto Use resource-box successor; never retry Train."""

    def run(self) -> TroopTrainingRecoveryResult:
        try:
            dispatch, unresolved = self._prior_action()
            old_post_path = Path(str(unresolved["post_path"]))
            old_frame = cv2.imread(str(old_post_path), cv2.IMREAD_COLOR)
            if old_frame is None:
                return self._result("blocked", "prior immediate-post frame could not be read")
            old_popup = recognize_auto_use_resource_popup(old_frame)
            if not old_popup.recognized or not old_popup.resource_boxes_selected or old_popup.warehouse_only:
                return self._result("blocked", "prior post does not prove the forbidden Auto Use resource-box popup")

            current = self.runtime.capture("forbidden-resource-popup-current")
            popup = recognize_auto_use_resource_popup(current.frame)
            if (
                not popup.recognized
                or not popup.resource_boxes_selected
                or popup.warehouse_only
                or popup.cancel_target is None
                or popup.confirm_target is None
            ):
                return self._result("blocked", "fresh frame does not prove the exact forbidden resource-box popup")
            troop_type = str(dispatch["target_identity"]).removeprefix("normal-train:")
            self.runtime.tap(
                current,
                target_identity="auto-use-resource-boxes:cancel",
                target_roi=popup.cancel_target,
                action_key=f"{dispatch['action_key']}:cancel-forbidden-resource-boxes",
            )
            time.sleep(self.post_input_delay)
            canceled = self.runtime.capture("forbidden-resource-popup-cancel-post")
            canceled_popup = recognize_auto_use_resource_popup(canceled.frame)
            canceled_training = recognize_training(canceled.frame)
            if (
                canceled_popup.recognized
                or not canceled_training.recognized
                or canceled_training.troop_type != troop_type
                or canceled_training.queue_active
            ):
                return self._result(
                    "blocked",
                    "Cancel did not positively restore the same empty troop training screen",
                    actions_completed=1,
                    recovered_action_key=str(dispatch["action_key"]),
                    troop_type=troop_type,
                )
            self.runtime.record_recovery(
                action_key=str(dispatch["action_key"]),
                previous_session=str(self.previous_session),
                previous_source_sha256=str(dispatch["source_sha256"]),
                previous_post_sha256=str(unresolved["post_sha256"]),
                current=canceled,
                expected_completion_timestamp="",
                reason="exact Auto Use resource-box successor canceled; normal Train failed without a queue or inventory consumption",
            )

            fresh = self.runtime.capture("forbidden-resource-popup-fresh-before-home")
            fresh_training = recognize_training(fresh.frame)
            if not fresh_training.recognized or fresh_training.troop_type != troop_type or fresh_training.queue_active:
                return self._result(
                    "blocked",
                    "fresh post-cancel frame is not the same empty troop training screen",
                    actions_completed=1,
                    recovered_action_key=str(dispatch["action_key"]),
                    troop_type=troop_type,
                )
            self.runtime.back(fresh, action_key=f"training:recovery:forbidden-popup:return-home:{fresh.sha256}")
            time.sleep(self.post_input_delay)
            final = self.runtime.capture("forbidden-resource-popup-final-home")
            final_home = recognize_home(final.frame, reset_identity="recovery")
            values = {
                "actions_completed": 2,
                "recovered_action_key": str(dispatch["action_key"]),
                "troop_type": troop_type,
                "selected_tier": canceled_training.selected_tier,
                "quantity": canceled_training.selected_quantity,
                "final_home_recognized": final_home.recognized,
            }
            if not final_home.recognized:
                return self._result("blocked", "forbidden popup was canceled but Home/Base was not recognized", **values)
            return self._result(
                "completed",
                "forbidden Auto Use resource-box popup canceled, Train terminally rejected, and Home/Base restored",
                **values,
            )
        except Exception as exc:
            return self._result("blocked", f"safe forbidden-popup recovery stop: {exc}")


class TroopTrainingResourceBoxAcquisitionRecoveryRoute(TroopTrainingUnresolvedRecoveryRoute):
    """Reconcile an unresolved Auto Use confirmation that applied boxes but started no queue."""

    def run(self) -> TroopTrainingRecoveryResult:
        try:
            dispatch, unresolved = self._prior_action()
            events = [
                json.loads(line)
                for line in (self.previous_session / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            source_event = next(
                event for event in events
                if event.get("type") == "capture" and event.get("sha256") == dispatch.get("source_sha256")
            )
            confirm_dispatch = next(
                event for event in events
                if event.get("type") == "dispatch"
                and event.get("action_key") == f"{dispatch['action_key']}:resource-box-confirm"
            )
            popup_event = next(
                event for event in events
                if event.get("type") == "capture" and event.get("sha256") == confirm_dispatch.get("source_sha256")
            )
            def event_path(event: dict[str, object]) -> Path:
                path = Path(str(event["path"]))
                return path if path.is_absolute() else Path.cwd() / path

            before_frame = cv2.imread(str(event_path(source_event)), cv2.IMREAD_COLOR)
            popup_frame = cv2.imread(str(event_path(popup_event)), cv2.IMREAD_COLOR)
            post_frame = cv2.imread(str(Path(str(unresolved["post_path"]))), cv2.IMREAD_COLOR)
            if before_frame is None or popup_frame is None or post_frame is None:
                return self._result("blocked", "prior resource-box evidence could not be read")
            before = recognize_training(before_frame)
            popup = recognize_auto_use_resource_popup(popup_frame)
            post = recognize_training(post_frame)
            troop_type = str(dispatch["target_identity"]).removeprefix("normal-train:")
            if troop_type not in TROOP_TYPES or before.selected_tier is None or before.selected_quantity is None:
                return self._result("blocked", "prior resource-box transaction identity is incomplete")
            values = {
                name: TrainingConfig(enabled=False, training_policy="disabled")
                for name in TROOP_TYPES
            }
            values[troop_type] = TrainingConfig(
                target_tier=before.selected_tier,
                quantity=before.selected_quantity,
                training_policy="continuous",
                allow_resource_boxes=True,
            )
            semantic = TrainingController(TroopTrainingConfig(**values), reset_identity="resource-box-recovery")
            if not semantic.prove_resource_boxes_applied(before, popup, post, troop_type):
                return self._result("blocked", "prior post does not positively prove resource boxes applied with an empty queue")

            current = self.runtime.capture("resource-box-acquisition-recovery-current")
            current_observation = recognize_training(current.frame)
            post_resources = post.resources_by_name()
            current_resources = current_observation.resources_by_name()
            if (
                not current_observation.recognized
                or current_observation.troop_type != troop_type
                or current_observation.selected_tier != before.selected_tier
                or current_observation.queue_active
                or set(current_resources) != set(RESOURCE_NAMES)
                or any(current_resources[name].held != post_resources[name].held for name in RESOURCE_NAMES)
            ):
                return self._result("blocked", "fresh frame does not match the proven queue-empty resource acquisition successor")
            self.runtime.record_recovery(
                action_key=str(dispatch["action_key"]),
                previous_session=str(self.previous_session),
                previous_source_sha256=str(dispatch["source_sha256"]),
                previous_post_sha256=str(unresolved["post_sha256"]),
                current=current,
                expected_completion_timestamp="",
                reason="resource boxes applied exactly as popup projected; queue remained empty and no Train retry occurred",
            )
            return self._result(
                "completed",
                "resource-box acquisition reconciled queue-empty; current training screen retained for a new exact transaction",
                recovered_action_key=str(dispatch["action_key"]),
                troop_type=troop_type,
                selected_tier=current_observation.selected_tier,
                quantity=current_observation.selected_quantity,
                actions_completed=0,
            )
        except Exception as exc:
            return self._result("blocked", f"safe resource-box acquisition recovery stop: {exc}")


class TroopTrainingIntegratedRoute:
    """Run each enabled type through one shared training screen and one native runtime port."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        config: TroopTrainingConfig,
        reset_identity: str,
        post_input_delay: float = 1.0,
        max_tier_swipes: int = 12,
        entry_only: bool = False,
        atlas_path: Path = DEFAULT_HOME_ATLAS,
        maximum_home_pans: int = 4,
        home_pan_settle_seconds: float = 1.0,
        persistence_path: Path | None = None,
        zoom_transport=None,
    ) -> None:
        self.runtime = runtime
        self.config = config
        self.reset_identity = reset_identity
        self.post_input_delay = post_input_delay
        self.max_tier_swipes = max_tier_swipes
        self.entry_only = entry_only
        self.atlas_path = atlas_path
        self.maximum_home_pans = maximum_home_pans
        self.home_pan_settle_seconds = home_pan_settle_seconds
        self.zoom_transport = zoom_transport
        # Session folders are ephemeral; reset-scoped initiation state must survive
        # controller/process recreation in the stable local capture root.
        persistence_path = persistence_path or (Path.cwd() / ".local-captures" / "troop-training-state.json")
        self.controller = TroopTrainingRuntimeController(config, reset_identity=reset_identity, persistence_path=persistence_path)
        self.actions_completed = 0
        self.completed_claims: list[dict[str, object]] = []
        self.warehouse_approvals: list[dict[str, object]] = []
        self.resource_box_approvals: list[dict[str, object]] = []
        self.training: list[dict[str, object]] = []
        self.entry_navigation: dict[str, object] = {}

    def _result(self, status: str, reason: str, *, final_home: bool = False) -> TroopTrainingRouteResult:
        resolved_config = self.config.resolved_profile()
        for troop_type in TROOP_TYPES:
            state = self.controller.semantic.states[troop_type]
            resolved_config[troop_type]["resolved_quantity"] = state.resolved_quantity
            resolved_config[troop_type]["daily_initiation_state"] = state.daily_initiation_state
            resolved_config[troop_type]["queue_state"] = state.queue_state
        return TroopTrainingRouteResult(
            status=status,
            reason=reason,
            actions_completed=self.actions_completed,
            completed_claims=tuple(self.completed_claims),
            warehouse_approvals=tuple(self.warehouse_approvals),
            resource_box_approvals=tuple(self.resource_box_approvals),
            training=tuple(self.training),
            daily_progress=self.controller.semantic.aggregate_daily(),
            final_home_recognized=final_home,
            entry_navigation=self.entry_navigation,
            session=str(self.runtime.session),
            resolved_config=resolved_config,
        )

    def _navigate_selected_facility(self, target):
        """Use only the shared planner plus the BlueStacks-owned adapter geometry."""

        atlas = load_home_atlas(self.atlas_path)
        building = atlas.lookup_building(target.building_id)
        localizer = BlueStacksHomeLocalizer(atlas, self.atlas_path)
        safe_region, calibration = bluestacks_direct_pan_contract()
        planner = TroopTrainingAtlasEntryPlanner(
            atlas,
            target,
            safe_region,
            calibration,
            maximum_pans=self.maximum_home_pans,
        )
        records: list[dict[str, object]] = []
        source = self.runtime.capture("entry-home-source")
        source_rejection = forbidden_atlas_entry_surface(source.frame)
        if source_rejection is not None:
            self.entry_navigation = {
                "mode": "entry_only" if self.entry_only else "full_training",
                "troop_type": target.troop_type,
                "building_id": target.building_id,
                "source_surface_rejection": source_rejection,
                "records": records,
                "train_dispatched": False,
            }
            return None, None, planner, source_rejection
        source_localization = localizer.localize(source.frame)
        canonical_source = _is_canonical_entry_localization(source_localization)
        self.entry_navigation = {
            "mode": "entry_only" if self.entry_only else "full_training",
            "troop_type": target.troop_type,
            "building_id": target.building_id,
            "safe_interaction_region_id": safe_region.region_id,
            "gesture_adapter_platform": calibration.platform,
            "records": records,
            "train_dispatched": False,
        }
        if canonical_source:
            self.entry_navigation["source_localization"] = asdict(source_localization)
        else:
            self.entry_navigation["initial_localization"] = asdict(source_localization)
            try:
                home = recognize_home(source.frame, reset_identity=self.reset_identity)
            except Exception as exc:
                return None, None, planner, f"home_zoom_recovery_home_hud_failed:{type(exc).__name__}"
            diagnostics = getattr(home, "diagnostics", {})
            if (
                getattr(home, "overlay_state", "none") != "none"
                or not isinstance(diagnostics, Mapping)
                or diagnostics.get("home_hud_signal") is not True
            ):
                return None, None, planner, "home_zoom_recovery_home_hud_not_positive"
            home_driver = BlueStacksLocalizeFirstHomeDriver(
                atlas,
                self.atlas_path,
                HomeReadyObservation(
                    True,
                    True,
                    VerifiedRuntimeIdentity(
                        "bluestacks-troop-training",
                        "supervised-troop-training",
                        "supervised-troop-training-server",
                        self.reset_identity,
                        RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
                        (f"reset:{self.reset_identity}", f"session:{self.runtime.session}"),
                    ),
                    False,
                    False,
                ),
                target.building_id,
                localizer=localizer,
                maximum_pans=self.maximum_home_pans,
                maximum_zoom_inputs=1,
            )
            immediate_before = self.runtime.capture("entry-home-zoom-01-immediate-before")
            immediate_surface_rejection = forbidden_atlas_entry_surface(immediate_before.frame)
            if immediate_surface_rejection is not None:
                return None, None, planner, immediate_surface_rejection
            try:
                immediate_home = recognize_home(
                    immediate_before.frame,
                    reset_identity=self.reset_identity,
                )
            except Exception as exc:
                return None, None, planner, f"home_zoom_recovery_home_hud_failed:{type(exc).__name__}"
            immediate_diagnostics = getattr(immediate_home, "diagnostics", None)
            immediate_overlay_state = getattr(immediate_home, "overlay_state", None)
            immediate_home_proof = bool(
                isinstance(immediate_diagnostics, Mapping)
                and immediate_diagnostics.get("home_hud_signal") is True
                and immediate_overlay_state == "none"
            )
            if not immediate_home_proof:
                return None, None, planner, "home_zoom_recovery_home_hud_not_positive"
            step = home_driver.observe(immediate_before.frame)
            recovery_record: dict[str, object] = {
                "immediate_before_sha256": immediate_before.sha256,
                "driver_digest": step.source_frame_sha256,
                "driver_disposition": step.disposition.value,
                "driver_reason": step.reason,
            }
            records.append({"zoom_recovery": recovery_record})
            if step.disposition is not HomeDriverDisposition.RECOVER_ZOOM:
                reason = (
                    f"home_zoom_recovery_blocked:{step.reason}"
                    if step.disposition is HomeDriverDisposition.BLOCKED
                    else f"home_zoom_recovery_unsupported:{step.disposition.value}"
                )
                return None, None, planner, reason
            if not self.runtime.execute:
                return None, None, planner, "dry-run-home-zoom-recovery-required"
            zoom_transport = self.zoom_transport
            if zoom_transport is None:
                runner = getattr(self.runtime, "runner", None)
                if runner is not None:
                    try:
                        zoom_transport = ScrcpyMotionEventZoomTransport(
                            adb=runner.executable,
                            serial=runner.serial,
                            evidence_directory=getattr(self.runtime, "session", None),
                        )
                    except Exception as exc:
                        return None, None, planner, f"home_zoom_transport_unavailable:{type(exc).__name__}"
            if zoom_transport is None:
                return None, None, planner, "home_zoom_transport_unavailable"
            declaration = NavigationRouteDeclaration(
                allowed_source_states=frozenset({"HOME_BASE"}),
                allowed_target_identities=frozenset({"home-zoom-out"}),
                allowed_gesture_classes=frozenset({"zoom_out"}),
            )
            guarded_runtime = (
                self.runtime
                if isinstance(self.runtime, NavigationGuardedRuntime)
                else NavigationGuardedRuntime(self.runtime, declaration)
            )
            try:
                guarded_runtime.dispatch_zoom_out(
                    immediate_before,
                    make_source_safety_facts(
                        recognized=immediate_home_proof,
                        source_state="HOME_BASE",
                        overlay_state=immediate_overlay_state,
                        frame_sha256=immediate_before.sha256,
                        captured_monotonic=immediate_before.captured_monotonic,
                    ),
                    transport=zoom_transport.zoom_out_once,
                )
                home_driver.record_zoom_input_dispatched(step.source_frame_sha256)
            except NavigationBoundaryError as exc:
                return None, None, planner, f"home_zoom_dispatch_blocked:{exc}"
            except Exception as exc:
                return None, None, planner, f"home_zoom_transport_failed:{type(exc).__name__}"
            self.actions_completed += 1
            immediate_post = self.runtime.capture("entry-home-zoom-01-immediate-post")
            if self.home_pan_settle_seconds > 0:
                time.sleep(self.home_pan_settle_seconds)
            settled = self.runtime.capture("entry-home-zoom-01-settled")
            recovery_record.update(
                {
                    "immediate_post_sha256": immediate_post.sha256,
                    "settled_sha256": settled.sha256,
                }
            )
            settled_surface_rejection = forbidden_atlas_entry_surface(settled.frame)
            if settled_surface_rejection is not None:
                return None, None, planner, settled_surface_rejection
            settled_step = home_driver.observe(settled.frame)
            recovery_record.update(
                {
                    "settled_driver_digest": settled_step.source_frame_sha256,
                    "settled_driver_reason": settled_step.reason,
                }
            )
            if frame_digest(immediate_before.frame) == frame_digest(settled.frame):
                return None, None, planner, "home_zoom_successor_unchanged"
            if not _is_canonical_entry_localization(settled_step.localization):
                return None, None, planner, f"home_zoom_successor_not_canonical:{settled_step.reason}"
            source_localization = settled_step.localization
            self.entry_navigation["source_localization"] = asdict(settled_step.localization)
            self.entry_navigation["home_zoom_recovery"] = recovery_record
        if not source_localization.recognized:
            return None, None, planner, "source_home_localization_failed"

        for ordinal in range(self.maximum_home_pans + 1):
            immediate_before = self.runtime.capture(f"entry-pan-{ordinal:02d}-immediate-before")
            surface_rejection = forbidden_atlas_entry_surface(immediate_before.frame)
            if surface_rejection is not None:
                return None, None, planner, surface_rejection
            localization = localizer.localize(immediate_before.frame)
            binding = bind_visible_building(immediate_before.frame, localization, building) if localization.recognized else None
            plan = planner.plan(localization, binding)
            plan_record = {
                "ordinal": ordinal,
                "localization": asdict(localization),
                "camera_origin": camera_origin(localization) if localization.recognized and localization.screen_to_atlas is not None else None,
                "plan": asdict(plan),
                "binding": asdict(binding) if binding is not None else None,
            }
            records.append(plan_record)
            if plan.disposition is PlanDisposition.PAN:
                if not self.runtime.execute:
                    return None, None, planner, "dry-run-calculated-pan-not-dispatched"
                if plan.drag_start is None or plan.drag_end is None:
                    return None, None, planner, "invalid_gesture_calibration"
                self.runtime.swipe(
                    immediate_before,
                    start=plan.drag_start,
                    end=plan.drag_end,
                    action_key=f"training:navigation:home-pan:{target.troop_type}:{ordinal}:{immediate_before.sha256}",
                    target_identity="home-camera-click-drag",
                )
                self.actions_completed += 1
                immediate_post = self.runtime.capture(f"entry-pan-{ordinal:02d}-immediate-post")
                if self.home_pan_settle_seconds > 0:
                    time.sleep(self.home_pan_settle_seconds)
                settled = self.runtime.capture(f"entry-pan-{ordinal:02d}-settled")
                surface_rejection = forbidden_atlas_entry_surface(settled.frame)
                if surface_rejection is not None:
                    return None, None, planner, surface_rejection
                settled_localization = localizer.localize(settled.frame)
                progress = planner.record_progress(localization, settled_localization)
                plan_record["pan"] = {
                    "immediate_before_sha256": immediate_before.sha256,
                    "immediate_post_sha256": immediate_post.sha256,
                    "settled_sha256": settled.sha256,
                    "settled_localization": asdict(settled_localization),
                    "progress": asdict(progress),
                }
                if not progress.accepted:
                    return None, None, planner, progress.reason
                continue
            if plan.disposition is PlanDisposition.COMPLETE and binding is not None:
                self.entry_navigation["final_binding"] = asdict(binding)
                self.entry_navigation["navigation_pans"] = planner.pan_count
                if not self.runtime.execute:
                    return immediate_before, binding, planner, "dry-run-bound-facility-not-tapped"
                return immediate_before, binding, planner, None
            if plan.disposition is PlanDisposition.BIND:
                return None, None, planner, "current_frame_facility_binding_required"
            return None, None, planner, plan.reason
        return None, None, planner, "maximum_pan_count"

    def _capture_home(self, label: str):
        last_captured = None
        last_observation = None
        for attempt in range(3):
            capture_label = label if attempt == 0 else f"{label}-recognition-retry-{attempt}"
            captured = self.runtime.capture(capture_label)
            observation = recognize_home(captured.frame, reset_identity=self.reset_identity)
            last_captured, last_observation = captured, observation
            if observation.recognized:
                return captured, observation
        return last_captured, last_observation

    def _capture_training(self, label: str):
        last_captured = None
        last_observation = None
        for attempt in range(2):
            capture_label = label if attempt == 0 else f"{label}-recognition-retry-{attempt}"
            captured = self.runtime.capture(capture_label)
            observation = recognize_training(captured.frame)
            last_captured, last_observation = captured, observation
            if observation.recognized:
                return captured, observation
        return last_captured, last_observation

    def _capture_radial(self, label: str, troop_type: str, facility_target):
        last_captured = None
        last_observation = None
        for attempt in range(2):
            capture_label = label if attempt == 0 else f"{label}-recognition-retry-{attempt}"
            captured = self.runtime.capture(capture_label)
            observation = recognize_radial_menu(
                captured.frame,
                troop_type=troop_type,
                facility_target=facility_target,
            )
            last_captured, last_observation = captured, observation
            if observation.recognized:
                return captured, observation
        return last_captured, last_observation

    def _record_reconciled_queue(self, captured, observation: TrainingScreenObservation, troop_type: str) -> None:
        state = self.controller.semantic.states[troop_type]
        self.training.append(
            {
                "troop_type": troop_type,
                "facility_identity": state.facility_identity,
                "selected_tier": observation.queue_tier,
                "quantity": observation.queue_quantity,
                "configured_quantity": state.configured_quantity,
                "quantity_mode": state.quantity_mode,
                "quantity_maximum": observation.quantity_maximum,
                "maximum_equality_proven": state.quantity_mode != "current_max" or observation.selected_quantity == observation.quantity_maximum,
                "queue_label": observation.queue_label,
                "queue_troop_type": observation.queue_troop_type,
                "queue_tier": observation.queue_tier,
                "queue_quantity": observation.queue_quantity,
                "displayed_training_duration_seconds": observation.training_duration_seconds,
                "duration_source": observation.diagnostics.get("duration_source"),
                "queue_spatially_associated": observation.diagnostics.get("queue_spatially_associated") is True,
                "queue_roi": observation.diagnostics.get("queue_band"),
                "expected_completion_timestamp": state.expected_completion_timestamp.isoformat() if state.expected_completion_timestamp else None,
                "queue_state": state.queue_state,
                "completion_policy": "read_only_existing_queue",
                "reset_identity": state.reset_identity,
                "training_policy": state.training_policy,
                "source_frame_hash": captured.sha256,
                "immediate_before_frame_hash": captured.sha256,
                "immediate_post_frame_hash": captured.sha256,
                "resources_before": [asdict(resource) for resource in observation.resources],
                "resources_after": [asdict(resource) for resource in observation.resources],
            }
        )

    def _wait(self) -> None:
        if self.post_input_delay > 0:
            time.sleep(self.post_input_delay)

    def _navigation_tap(self, captured, *, identity: str, roi, action_key: str) -> None:
        self.runtime.tap(captured, target_identity=identity, target_roi=roi, action_key=action_key)
        self.actions_completed += 1
        self._wait()

    def _claim_completed_tab(self, captured, observation: TrainingScreenObservation):
        troop_type = observation.troop_type
        if troop_type is None or not observation.completion_ready:
            return captured, observation, None
        recognition = recognize_training_with_targets(captured.frame)
        target = recognition.target(f"tab:{troop_type}")
        action_key = make_action_key(troop_type, self.reset_identity, captured.sha256, "claim")
        if target is None or self.controller.semantic.plan_claim(observation, action_key=action_key) != "authorize_claim":
            return None, None, "completed troop claim was not authorizeable"
        self.runtime.tap(
            captured,
            target_identity=f"tab:{troop_type}:claim-completed",
            target_roi=target,
            action_key=action_key,
            consequential=False,
        )
        self.actions_completed += 1
        self._wait()
        post_capture, post = self._capture_training("completed-claim-immediate-post")
        if not self.controller.semantic.reconcile_claim(observation, post, action_key=action_key):
            self.runtime.reconcile(action_key, "unresolved", post_capture, "completed troop state did not clear positively")
            return None, None, "completed troop claim unresolved"
        self.runtime.reconcile(action_key, "confirmed", post_capture, "completed troop claim cleared on same-type tab")
        self.completed_claims.append(
            {
                "troop_type": troop_type,
                "action_key": action_key,
                "source_frame_hash": captured.sha256,
                "post_frame_hash": post_capture.sha256,
                "batch_identity": observation.completion_batch_id,
            }
        )
        state = self.controller.semantic.states[troop_type]
        self.training.append(
            {
                "troop_type": troop_type,
                "facility_identity": state.facility_identity,
                "selected_tier": observation.selected_tier,
                "quantity": observation.selected_quantity,
                "configured_quantity": state.configured_quantity,
                "quantity_mode": state.quantity_mode,
                "quantity_maximum": observation.quantity_maximum,
                "maximum_equality_proven": state.quantity_mode != "current_max" or observation.selected_quantity == observation.quantity_maximum,
                "queue_label": None,
                "queue_troop_type": None,
                "queue_tier": None,
                "queue_quantity": None,
                "displayed_training_duration_seconds": None,
                "duration_source": None,
                "queue_spatially_associated": False,
                "queue_roi": observation.diagnostics.get("queue_band"),
                "expected_completion_timestamp": None,
                "queue_state": state.queue_state,
                "completion_policy": "completed_batch_claim_reconciled",
                "batch_identity": observation.completion_batch_id,
                "action_key": action_key,
                "daily_initiation_state": state.daily_initiation_state,
                "reset_identity": state.reset_identity,
                "training_policy": state.training_policy,
                "source_frame_hash": captured.sha256,
                "immediate_before_frame_hash": captured.sha256,
                "immediate_post_frame_hash": post_capture.sha256,
                "resources_before": [asdict(resource) for resource in observation.resources],
                "resources_after": [asdict(resource) for resource in post.resources],
            }
        )
        return post_capture, post, None

    def _switch_tab(self, captured, observation: TrainingScreenObservation, troop_type: str):
        if observation.troop_type == troop_type:
            return captured, observation, None
        captured, observation, error = self._claim_completed_tab(captured, observation)
        if error:
            return None, None, error
        captured = self.runtime.capture(f"tab-{troop_type}-immediate-before")
        recognition = recognize_training_with_targets(captured.frame)
        observation = recognition.observation
        if not observation.recognized or observation.overlay_state != "none":
            return None, None, f"tab source could not be freshly recognized for {troop_type}"
        target = recognition.target(f"tab:{troop_type}")
        if target is None:
            return None, None, f"tab target not bound for {troop_type}"
        if observation.completion_ready:
            return None, None, "completed tab remained ready after claim reconciliation"
        self._navigation_tap(
            captured,
            identity=f"tab:{troop_type}",
            roi=target,
            action_key=f"training:navigation:tab:{troop_type}:{captured.sha256}",
        )
        post_capture, post = self._capture_training(f"tab-{troop_type}-post")
        if not post.recognized or post.troop_type != troop_type:
            return None, None, f"tab successor did not recognize {troop_type}"
        if post.completion_ready:
            # A tab selection with an unproven pre-state may have claimed a batch.  It is
            # unresolved, never silently accepted or retried.
            return None, None, f"tab selection produced an unpreauthorized completed claim for {troop_type}"
        return post_capture, post, None

    def _select_tier(self, captured, observation: TrainingScreenObservation, troop_type: str):
        config = self.config.for_type(troop_type)
        if config.target_tier is None:
            return None, None, "target tier is not explicitly configured"
        seen_windows: set[tuple[int, ...]] = set()
        for ordinal in range(self.max_tier_swipes + 1):
            plan = self.controller.semantic.plan_tier(observation, troop_type)
            candidate = observation.tier(config.target_tier)
            if plan == "tier_selected":
                if candidate is None or candidate.locked:
                    return None, None, "configured tier is not positively unlocked"
                return captured, observation, None
            if plan == "reject_locked_tier":
                return None, None, "configured tier is locked or question-marked"
            if plan != "select_tier":
                return None, None, plan
            if candidate is not None:
                if candidate.locked or candidate.target_roi is None:
                    return None, None, "visible configured tier is locked or ambiguous"
                # Full-screen OCR used to discover a newly visible low tier can
                # consume most of the runtime's source-frame age budget.  Take
                # a fresh native authorization frame and rebind the exact card
                # before dispatch; never tap from the discovery frame.
                fresh_capture, fresh_observation = self._capture_training(
                    f"tier-{troop_type}-immediate-before"
                )
                fresh_candidate = fresh_observation.tier(config.target_tier)
                if (
                    not fresh_observation.recognized
                    or fresh_observation.troop_type != troop_type
                    or fresh_observation.queue_active
                    or fresh_observation.overlay_state != "none"
                    or fresh_candidate is None
                    or fresh_candidate.locked
                    or fresh_candidate.target_roi is None
                ):
                    return None, None, "configured tier could not be freshly rebound before selection"
                self._navigation_tap(
                    fresh_capture,
                    identity=f"tier:{config.target_tier}",
                    roi=fresh_candidate.target_roi,
                    action_key=f"training:navigation:tier:{troop_type}:{config.target_tier}:{fresh_capture.sha256}",
                )
                post_capture, post = self._capture_training(f"tier-{troop_type}-post")
                selected = post.tier(config.target_tier)
                if not post.recognized or post.selected_tier != config.target_tier or selected is None or selected.locked:
                    return None, None, "configured tier selection was not positively verified"
                return post_capture, post, None
            visible = sorted(
                (item for item in observation.visible_tiers if item.visible),
                key=lambda item: item.tier,
            )
            unlocked = [
                item
                for item in visible
                if not item.locked and not item.question_mark and item.target_roi is not None
            ]
            window = tuple(item.tier for item in unlocked)
            if not window or window in seen_windows or ordinal == self.max_tier_swipes:
                return None, None, "tier carousel repeated, had no progress, or exceeded bound"
            seen_windows.add(window)
            lower_target = config.target_tier < window[0]
            upper_target = config.target_tier > window[-1]
            blocking_locked = (
                any(item.locked and item.tier < window[0] for item in visible)
                if lower_target
                else any(item.locked and item.tier > window[-1] for item in visible)
                if upper_target
                else True
            )
            if (
                len(unlocked) < 2
                or not (lower_target or upper_target)
                or blocking_locked
                or any(right - left != 1 for left, right in zip(window, window[1:]))
            ):
                return None, None, "visible tier strip is locked, gapped, or spatially ambiguous"
            minimum, maximum = min(window), max(window)
            if config.target_tier > maximum:
                direction = -1
            elif config.target_tier < minimum:
                direction = 1
            else:
                return None, None, "configured tier lies in an unrecognized carousel gap"
            rois = [item.target_roi for item in unlocked if item.target_roi is not None]
            centers_x = [int((roi[0] + roi[2]) / 2) for roi in rois]
            centers_y = [int((roi[1] + roi[3]) / 2) for roi in rois]
            # Keep the gesture inside the tier-card image band.  The prior
            # edge-clamped start (e.g. x=62) can be ignored by BlueStacks as
            # an OS-edge gesture; use card centers and a bounded interior end.
            strip_y = max(840, min(960, int(sum(centers_y) / len(centers_y))))
            left_x, right_x = min(centers_x), max(centers_x)
            if direction < 0:
                start_x = min(700, max(100, right_x))
                end_x = max(100, min(680, left_x - 240))
            else:
                start_x = max(100, min(700, left_x))
                end_x = min(680, max(start_x + 200, right_x + 280))
            if abs(end_x - start_x) < 160:
                return None, None, "tier carousel gesture had insufficient bounded travel"
            start = (start_x, strip_y)
            end = (end_x, strip_y)
            self.runtime.swipe(
                captured,
                start=start,
                end=end,
                action_key=f"training:navigation:swipe:{troop_type}:{ordinal}:{captured.sha256}",
            )
            self.actions_completed += 1
            self._wait()
            captured, observation = self._capture_training(f"tier-swipe-{troop_type}-{ordinal}-post")
            if not observation.recognized:
                return None, None, "tier swipe successor is not a recognized training screen"
            # Rebind the configured card immediately after every swipe.  A
            # target can enter the visible window on the swipe successor; do
            # not issue another gesture before tapping/revalidating that
            # current-frame card.
            post_candidate = observation.tier(config.target_tier)
            if post_candidate is not None:
                if post_candidate.locked or post_candidate.target_roi is None:
                    return None, None, "visible configured tier is locked or ambiguous"
                if observation.selected_tier == config.target_tier:
                    return captured, observation, None
                self._navigation_tap(
                    captured,
                    identity=f"tier:{config.target_tier}",
                    roi=post_candidate.target_roi,
                    action_key=f"training:navigation:tier:{troop_type}:{config.target_tier}:{captured.sha256}",
                )
                selected_capture, selected_observation = self._capture_training(
                    f"tier-{troop_type}-post"
                )
                selected = selected_observation.tier(config.target_tier)
                if (
                    not selected_observation.recognized
                    or selected_observation.selected_tier != config.target_tier
                    or selected is None
                    or selected.locked
                ):
                    return None, None, "configured tier selection was not positively verified"
                return selected_capture, selected_observation, None
            post_window = tuple(
                item.tier
                for item in sorted(observation.visible_tiers, key=lambda item: item.tier)
                if item.visible and not item.locked and not item.question_mark and item.target_roi is not None
            )
            if post_window == window:
                return None, None, "tier swipe produced no bounded carousel progress"
        return None, None, "tier selection stopped safely"

    def _set_quantity(self, captured, observation: TrainingScreenObservation, troop_type: str):
        config = self.config.for_type(troop_type)
        if config.quantity_mode == "current_max":
            if observation.quantity_maximum is None or observation.quantity_maximum <= 0:
                return None, None, "current numeric maximum is unresolved"
            quantity = observation.quantity_maximum
        else:
            quantity = config.quantity
        if quantity is None:
            return None, None, "configured quantity is unresolved"
        if observation.selected_quantity == quantity:
            return captured, observation, None
        captured, observation = self._capture_training(f"quantity-{troop_type}-immediate-before")
        if (
            not observation.recognized
            or observation.troop_type != troop_type
            or observation.queue_active
            or observation.overlay_state != "none"
            or observation.selected_tier != config.target_tier
            or observation.normal_train_target is None
        ):
            return None, None, "quantity editor could not be freshly authorized"
        if config.quantity_mode == "current_max":
            if observation.quantity_maximum is None or observation.quantity_maximum <= 0:
                return None, None, "current numeric maximum is unresolved on immediate-before"
            quantity = observation.quantity_maximum
        if observation.selected_quantity == quantity:
            return captured, observation, None
        self._navigation_tap(
            captured,
            identity="quantity-editor",
            roi=QUANTITY_BAND,
            action_key=f"training:navigation:quantity-editor:{troop_type}:{captured.sha256}",
        )
        editor_capture = self.runtime.capture("quantity-editor-before-text")
        # The editor can display a one-digit resource-limited value while retaining a previous
        # four-digit buffer. Clear the contract maximum width every time before exact entry.
        max_digits = len(str(observation.quantity_maximum or quantity or 1000))
        self.runtime.clear_numeric_text(
            editor_capture,
            max_digits=max_digits,
            action_key=f"training:navigation:quantity-clear:{troop_type}:{editor_capture.sha256}",
        )
        self.actions_completed += 1
        self._wait()
        editor_after_clear = self.runtime.capture("quantity-editor-after-clear")
        self.runtime.type_text(
            editor_after_clear,
            text=str(quantity),
            action_key=f"training:navigation:quantity-text:{troop_type}:{editor_after_clear.sha256}",
        )
        self.actions_completed += 1
        typed_capture = self.runtime.capture("quantity-editor-after-text")
        self.runtime.press_key(
            typed_capture,
            key="ENTER",
            action_key=f"training:navigation:quantity-enter:{troop_type}:{typed_capture.sha256}",
        )
        self.actions_completed += 1
        self._wait()
        post_capture, post = self._capture_training(f"quantity-{troop_type}-post")
        if not post.recognized or post.selected_quantity != quantity:
            return None, None, "configured quantity was not displayed exactly"
        return post_capture, post, None

    def _train(self, captured, observation: TrainingScreenObservation, troop_type: str):
        # Full-frame OCR can consume the native runtime's complete source-age budget.  Re-run
        # the training recognizer on one fresh native frame, then use that exact observation for
        # every semantic gate and the consequential dispatch binding.
        captured, observation = self._capture_training(
            f"{troop_type}-train-immediate-before"
        )
        if not observation.recognized:
            return None, None, "fresh Train frame was not recognized"
        if observation.troop_type != troop_type:
            return None, None, f"fresh Train frame troop type mismatch: expected {troop_type}"
        plan = self.controller.semantic.plan_training(observation, troop_type)
        if plan not in {"authorize_normal_train", "authorize_normal_train_expected_warehouse"}:
            return None, None, plan
        target = observation.normal_train_target
        if target is None:
            return None, None, "normal Train target is not positively bound"
        action_key = make_action_key(troop_type, self.reset_identity, captured.sha256, "train")
        decision = self.controller.observe_training(observation, troop_type)
        if decision.action != "start_training":
            return None, None, decision.reason
        self.controller.dispatch_started(troop_type, action_key)
        dispatched_at = datetime.now(timezone.utc)
        self.runtime.tap(
            captured,
            target_identity=f"normal-train:{troop_type}",
            target_roi=target,
            action_key=action_key,
            consequential=True,
        )
        self.actions_completed += 1
        self._wait()
        post_capture, post = self._capture_training(f"{troop_type}-train-immediate-post")
        resource_popup = recognize_auto_use_resource_popup(post_capture.frame)
        if resource_popup.recognized:
            # Shooter and Rider never authorize resource-box use, even if a caller
            # supplied a permissive legacy config.  Their exact popup is canceled.
            if troop_type not in {"fighter", "vehicle"}:
                resource_popup = replace(resource_popup, recognized=True)
            # Rebind both buttons and every resource amount from a fresh native frame before the
            # one permitted continuation input.  Confirm is never inferred from the stale
            # immediate-post frame.
            popup_capture = self.runtime.capture(f"{troop_type}-resource-box-popup-immediate-before")
            resource_popup = recognize_auto_use_resource_popup(popup_capture.frame)
            popup_plan = (
                "reject_resource_boxes_disabled"
                if troop_type not in {"fighter", "vehicle"}
                else self.controller.semantic.plan_resource_box_continuation(
                observation,
                resource_popup,
                troop_type,
                )
            )
            if popup_plan == "authorize_resource_box_confirmation":
                if resource_popup.confirm_target is None:
                    self.runtime.reconcile(action_key, "unresolved", popup_capture, "resource-box Confirm target disappeared")
                    return None, None, "resource-box continuation unresolved"
                self.runtime.tap(
                    popup_capture,
                    target_identity=f"resource-box-confirm:{troop_type}",
                    target_roi=resource_popup.confirm_target,
                    action_key=f"{action_key}:resource-box-confirm",
                    continuation_of=action_key,
                )
                self.actions_completed += 1
                self._wait()
                confirmed_capture, confirmed = self._capture_training(f"{troop_type}-resource-box-immediate-post")
                approval = {
                    "troop_type": troop_type,
                    "action_key": action_key,
                    "configured_quantity": self.controller.semantic.resolved_quantity(observation, troop_type),
                    "quantity_mode": self.config.for_type(troop_type).quantity_mode,
                    "popup_frame_hash": popup_capture.sha256,
                    "post_frame_hash": confirmed_capture.sha256,
                    "resources_after_use": [asdict(resource) for resource in resource_popup.resources_after_use],
                }
                if (
                    confirmed.recognized
                    and confirmed.queue_active
                    and confirmed.troop_type == troop_type
                    and confirmed.selected_tier == observation.selected_tier
                    and confirmed.selected_quantity == self.controller.semantic.resolved_quantity(observation, troop_type)
                ):
                    self.resource_box_approvals.append({**approval, "successor": "active_queue"})
                    post_capture, post = confirmed_capture, confirmed
                elif self.controller.semantic.prove_resource_boxes_applied(
                    observation,
                    resource_popup,
                    confirmed,
                    troop_type,
                ):
                    before_resources = observation.resources_by_name()
                    applied = {
                        resource.name: (resource.held or 0) - (before_resources[resource.name].held or 0)
                        for resource in resource_popup.resources_after_use
                    }
                    failed = self.controller.reconcile_failed_started(
                        troop_type,
                        confirmed,
                        action_key=action_key,
                        reason="resource_boxes_applied_queue_empty",
                    )
                    if failed.phase != TrainingPhase.BLOCKED:
                        self.runtime.reconcile(action_key, "unresolved", confirmed_capture, failed.reason)
                        return None, None, failed.reason
                    self.runtime.reconcile(
                        action_key,
                        "failed_confirmed",
                        confirmed_capture,
                        "resource boxes positively applied; queue remained empty and requires a new exact Train transaction",
                    )
                    self.resource_box_approvals.append(
                        {**approval, "successor": "resources_applied_queue_empty", "applied_amounts": applied}
                    )
                    return confirmed_capture, confirmed, RESOURCE_BOXES_APPLIED_REAPPLY_TRAINING
                else:
                    self.runtime.reconcile(action_key, "unresolved", confirmed_capture, "resource-box confirmation did not prove resource acquisition or the exact active queue")
                    return None, None, "resource-box continuation unresolved"
            elif popup_plan == "reject_resource_boxes_disabled":
                if resource_popup.cancel_target is None:
                    self.runtime.reconcile(action_key, "unresolved", popup_capture, "resource-box Cancel target disappeared")
                    return None, None, "resource-box disabled continuation unresolved"
                self.runtime.tap(
                    popup_capture,
                    target_identity=f"resource-box-cancel:{troop_type}",
                    target_roi=resource_popup.cancel_target,
                    action_key=f"{action_key}:resource-box-cancel",
                    continuation_of=action_key,
                )
                self.actions_completed += 1
                self._wait()
                canceled_capture, canceled = self._capture_training(f"{troop_type}-resource-box-cancel-immediate-post")
                failed = self.controller.reconcile_failed_started(
                    troop_type,
                    canceled,
                    action_key=action_key,
                    reason="resource_boxes_disabled",
                )
                if failed.phase != TrainingPhase.BLOCKED:
                    self.runtime.reconcile(action_key, "unresolved", canceled_capture, failed.reason)
                    return None, None, failed.reason
                self.runtime.reconcile(action_key, "failed_confirmed", canceled_capture, "resource boxes disabled; exact popup canceled and queue remained empty")
                return canceled_capture, canceled, "resource boxes are required but allow_resource_boxes is false"
            else:
                self.runtime.reconcile(action_key, "unresolved", popup_capture, popup_plan)
                return None, None, f"resource-box popup rejected: {popup_plan}"
        elif post.warehouse_popup:
            if post.warehouse_confirm_target is None or post.premium_popup or post.forbidden_controls or not post.resource_shortage:
                self.runtime.reconcile(action_key, "unresolved", post_capture, "warehouse confirmation was not exact warehouse-only")
                return None, None, "ambiguous or forbidden warehouse confirmation"
            self.runtime.tap(
                post_capture,
                target_identity=f"warehouse-confirm:{troop_type}",
                target_roi=post.warehouse_confirm_target,
                action_key=f"{action_key}:warehouse-confirm",
                continuation_of=action_key,
            )
            self.actions_completed += 1
            self._wait()
            confirmed_capture, confirmed = self._capture_training(f"{troop_type}-warehouse-immediate-post")
            if not confirmed.queue_active:
                self.runtime.reconcile(action_key, "unresolved", confirmed_capture, "warehouse confirmation did not prove an active timed queue")
                return None, None, "warehouse continuation unresolved"
            post_capture, post = confirmed_capture, confirmed
            self.warehouse_approvals.append(
                {
                    "troop_type": troop_type,
                    "action_key": action_key,
                    "post_frame_hash": confirmed_capture.sha256,
                    "shortage": post.resource_shortage,
                }
            )
        elif not post.queue_active:
            self.runtime.reconcile(action_key, "unresolved", post_capture, "normal Train did not prove an active timed queue")
            return None, None, "training initiation unresolved"
        reconciled = self.controller.reconcile_started(troop_type, observation, post, action_key=action_key, dispatched_at=dispatched_at)
        if reconciled.action != "yield":
            self.runtime.reconcile(action_key, "unresolved", post_capture, reconciled.reason)
            return None, None, reconciled.reason
        self.runtime.reconcile(action_key, "confirmed", post_capture, "active queue, quantity, tier, and timer positively recognized")
        state = self.controller.states[troop_type]
        self.training.append(
            {
                "troop_type": troop_type,
                "facility_identity": state.facility_identity,
                "selected_tier": state.target_tier,
                "quantity": state.resolved_quantity,
                "configured_quantity": state.configured_quantity,
                "quantity_mode": state.quantity_mode,
                "quantity_maximum": observation.quantity_maximum,
                "maximum_equality_proven": self.config.for_type(troop_type).quantity_mode != "current_max" or (
                    observation.quantity_maximum is not None
                    and observation.selected_quantity == observation.quantity_maximum
                ),
                "queue_label": post.queue_label,
                "queue_troop_type": post.queue_troop_type,
                "queue_tier": post.queue_tier,
                "queue_quantity": post.queue_quantity,
                "duration_source": post.diagnostics.get("duration_source"),
                "queue_spatially_associated": post.diagnostics.get("queue_spatially_associated") is True,
                "queue_roi": post.diagnostics.get("queue_band"),
                "resources_before": [asdict(resource) for resource in observation.resources],
                "resources_after": [asdict(resource) for resource in post.resources],
                "reset_identity": state.reset_identity,
                "action_key": action_key,
                "source_frame_hash": captured.sha256,
                "immediate_before_frame_hash": captured.sha256,
                "immediate_post_frame_hash": post_capture.sha256,
                "displayed_training_duration_seconds": state.training_duration_seconds,
                "dispatch_timestamp": dispatched_at.isoformat(),
                "expected_completion_timestamp": state.expected_completion_timestamp.isoformat() if state.expected_completion_timestamp else None,
                "queue_state": state.queue_state,
                "training_policy": state.training_policy,
                "next_eligible_timestamp": state.next_eligible_timestamp.isoformat() if state.next_eligible_timestamp else None,
            }
        )
        return post_capture, post, None

    def _return_home(
        self,
        captured,
        *,
        status: str = "completed",
        reason: str = "all enabled troop workflows reconciled and returned Home/Base",
    ) -> TroopTrainingRouteResult:
        fresh = self.runtime.capture("return-home-immediate-before")
        stable_bands = (
            (180, 0, 620, 70),
            (180, 65, 615, 185),
            (40, 740, 760, 970),
            (90, 1040, 710, 1100),
        )
        if not all(
            np.array_equal(captured.frame[y1:y2, x1:x2], fresh.frame[y1:y2, x1:x2])
            for x1, y1, x2, y2 in stable_bands
        ):
            return self._result("blocked", "fresh return-Home frame changed in a bound training identity region")
        self.runtime.back(fresh, action_key=f"training:navigation:return-home:{fresh.sha256}")
        self.actions_completed += 1
        self._wait()
        final_capture, final_home = self._capture_home("final-home")
        final_training = (
            recognize_training(final_capture.frame)
            if isinstance(final_capture.frame, np.ndarray)
            else None
        )
        if not _canonical_home_proof(
            final_capture.frame,
            final_home,
            self.atlas_path,
            training=final_training,
        ):
            return self._result("blocked", "final Home/Base canonical Atlas postcondition not recognized")
        atlas = load_home_atlas(self.atlas_path)
        terminal_localization = BlueStacksHomeLocalizer(atlas, self.atlas_path).localize(final_capture.frame)
        self.entry_navigation["terminal_home_localization"] = asdict(terminal_localization)
        self.entry_navigation["terminal_home_frame_hash"] = final_capture.sha256
        if not terminal_localization.recognized or terminal_localization.zoom_identity != ZoomIdentity.FULLY_ZOOMED_OUT:
            return self._result("blocked", "terminal Home atlas localization/canonical zoom not recognized")
        if self.training:
            self.training[-1]["terminal_home_frame_hash"] = final_capture.sha256
            self.training[-1]["terminal_home_recognized"] = True
        self.controller.final_home()
        return self._result(status, reason, final_home=True)

    def _run_training_tabs(self, captured, observation: TrainingScreenObservation, enabled_types: list[str], first: str) -> TroopTrainingRouteResult:
        self.controller.begin_facility(first, captured.sha256)
        for troop_type in enabled_types:
            captured, observation, error = self._switch_tab(captured, observation, troop_type)
            if error:
                return self._result("unresolved" if self.runtime.in_flight_action else "blocked", error)
            self.controller.begin_facility(troop_type, captured.sha256)
            if observation.completion_ready:
                captured, observation, error = self._claim_completed_tab(captured, observation)
                if error:
                    return self._result("blocked", f"{troop_type}: {error}")
                if self.config.for_type(troop_type).training_policy == "once_daily":
                    continue
            if observation.queue_active:
                queue_plan = self.controller.semantic.reconcile_active_queue(observation, troop_type)
                if queue_plan != "active_queue_reconciled":
                    return self._result("blocked", f"{troop_type}: {queue_plan}")
                self._record_reconciled_queue(captured, observation, troop_type)
                continue
            captured, observation, error = self._select_tier(captured, observation, troop_type)
            if error:
                return self._result("blocked", f"{troop_type}: {error}")
            captured, observation, error = self._set_quantity(captured, observation, troop_type)
            if error:
                return self._result("blocked", f"{troop_type}: {error}")
            captured, observation, error = self._train(captured, observation, troop_type)
            if error == RESOURCE_BOXES_APPLIED_REAPPLY_TRAINING:
                captured, observation, error = self._set_quantity(captured, observation, troop_type)
                if error:
                    return self._result("blocked", f"{troop_type}: resource boxes applied but exact quantity could not be restored: {error}")
                captured, observation, error = self._train(captured, observation, troop_type)
            if error:
                if self.runtime.in_flight_action is None and captured is not None and observation is not None and observation.recognized:
                    return self._return_home(captured, status="blocked", reason=f"{troop_type}: {error}")
                return self._result("unresolved" if self.runtime.in_flight_action else "blocked", f"{troop_type}: {error}")
        return self._return_home(captured)

    def run(self) -> TroopTrainingRouteResult:
        self.config.validate()
        target = first_enabled_entry_target(self.config)
        if target is None:
            return self._result("completed", "all troop workflows disabled; no input authorized", final_home=True)
        enabled_types = [troop_type for troop_type in TROOP_TYPES if self.config.for_type(troop_type).enabled and self.config.for_type(troop_type).training_policy != "disabled"]
        first = target.troop_type
        try:
            current = self.runtime.capture("training-route-current-source")
            current_radial = recognize_radial_menu(current.frame, troop_type=first)
            if (
                current_radial.recognized
                and current_radial.facility_identity == FACILITY_BY_TYPE[first]
                and current_radial.train_target is not None
                and current_radial.overlay_state == "none"
            ):
                self.entry_navigation.update(
                    {
                        "mode": "retained_radial_continuation",
                        "initial_radial_binding": asdict(current_radial),
                    }
                )
                fresh_radial_capture, fresh_radial = self._capture_radial(
                    "retained-radial-immediate-before-train-menu",
                    first,
                    None,
                )
                if (
                    fresh_radial_capture is None
                    or fresh_radial is None
                    or not fresh_radial.recognized
                    or fresh_radial.facility_identity != FACILITY_BY_TYPE[first]
                    or fresh_radial.train_target is None
                    or fresh_radial.overlay_state != "none"
                ):
                    return self._result(
                        "blocked",
                        f"retained {first} radial immediate-before rebind failed: expected {FACILITY_BY_TYPE[first]} with Train",
                    )
                self.entry_navigation["radial_binding"] = asdict(fresh_radial)
                self._navigation_tap(
                    fresh_radial_capture,
                    identity=f"train-menu:{first}",
                    roi=fresh_radial.train_target,
                    action_key=f"training:navigation:train-menu:{first}:{fresh_radial_capture.sha256}",
                )
                captured, observation = self._capture_training("training-screen-source")
                if not observation.recognized or observation.troop_type != first:
                    return self._result("blocked", "complete training screen not recognized")
                return self._run_training_tabs(captured, observation, enabled_types, first)
            facility_capture, facility_binding, entry_planner, error = self._navigate_selected_facility(target)
            if error is not None:
                status = "dry-run" if error.startswith("dry-run-") else "blocked"
                return self._result(status, error)
            if facility_capture is None or facility_binding is None:
                return self._result("blocked", "fresh current-frame facility binding missing")
            self._navigation_tap(
                facility_capture,
                identity=f"facility:{first}",
                roi=facility_binding.target_roi,
                action_key=f"training:navigation:facility:{first}:{facility_capture.sha256}",
            )
            menu_capture, menu = self._capture_radial("facility-radial-menu", first, facility_binding.target_roi)
            if recognize_auto_use_resource_popup(menu_capture.frame).recognized or recognize_training(menu_capture.frame).recognized:
                return self._result("blocked", "unexpected consequential training or resource surface after facility entry")
            if not entry_planner.radial_is_exact(menu):
                return self._result("blocked", f"{first} radial menu or Train control not recognized")
            if self.entry_only:
                self.entry_navigation["radial_binding"] = asdict(menu)
                fresh_menu_capture, fresh_menu = self._capture_radial(
                    "entry-only-radial-immediate-before-toggle-close",
                    first,
                    facility_binding.target_roi,
                )
                if not entry_planner.radial_is_exact(fresh_menu):
                    return self._result("blocked", "entry-only radial could not be freshly rebound before safe toggle close")
                atlas = load_home_atlas(self.atlas_path)
                localizer = BlueStacksHomeLocalizer(atlas, self.atlas_path)
                close_localization = localizer.localize(fresh_menu_capture.frame)
                close_binding = bind_radial_exterior_close(
                    fresh_menu_capture.frame,
                    close_localization,
                    atlas,
                    fresh_menu,
                    troop_type=first,
                )
                if close_binding is None:
                    return self._result("blocked", "entry-only safe radial exterior close target could not be bound")
                self.entry_navigation["close_binding"] = asdict(close_binding)
                self.runtime.tap(
                    fresh_menu_capture,
                    target_identity=f"radial-exterior-close:{first}",
                    target_roi=close_binding.target_roi,
                    action_key=f"training:navigation:entry-only-exterior-close:{first}:{fresh_menu_capture.sha256}",
                )
                self.actions_completed += 1
                self._wait()
                final = self.runtime.capture("entry-only-final-home")
                remaining_radial = recognize_radial_menu(
                    final.frame,
                    troop_type=first,
                    facility_target=facility_binding.target_roi,
                )
                if remaining_radial.recognized and remaining_radial.train_target is not None:
                    return self._result("blocked", "entry-only exterior tap did not close the radial")
                final_surface_rejection = forbidden_atlas_entry_surface(final.frame)
                if final_surface_rejection is not None:
                    self.entry_navigation["final_surface_rejection"] = final_surface_rejection
                    return self._result("blocked", "entry-only Back reached a forbidden or modal surface")
                final_localization = localizer.localize(final.frame)
                self.entry_navigation["final_localization"] = asdict(final_localization)
                if not final_localization.recognized:
                    return self._result("blocked", "entry-only Back did not recover fresh canonical Home")
                return self._result(
                    "completed",
                    "entry-only facility radial and Train control recognized; Train not dispatched; canonical Home recovered",
                    final_home=True,
                )
            fresh_menu_capture, fresh_menu = self._capture_radial(
                "facility-radial-immediate-before-train-menu",
                first,
                facility_binding.target_roi,
            )
            if fresh_menu_capture is None or fresh_menu is None or not entry_planner.radial_is_exact(fresh_menu):
                return self._result(
                    "blocked",
                    f"fresh {first} radial immediate-before rebind failed: expected {FACILITY_BY_TYPE[first]} with Train",
                )
            self.entry_navigation["radial_binding"] = asdict(fresh_menu)
            self._navigation_tap(
                fresh_menu_capture,
                identity=f"train-menu:{first}",
                roi=fresh_menu.train_target,
                action_key=f"training:navigation:train-menu:{first}:{fresh_menu_capture.sha256}",
            )
            captured, observation = self._capture_training("training-screen-source")
            if not observation.recognized or observation.troop_type != first:
                return self._result("blocked", "complete training screen not recognized")
            return self._run_training_tabs(captured, observation, enabled_types, first)
        except Exception as exc:
            if self.runtime.in_flight_action is not None:
                return self._result("unresolved", f"runtime failure after consequential action: {exc}")
            return self._result("blocked", f"safe route stop: {exc}")


def _load_config(args: argparse.Namespace) -> TroopTrainingConfig:
    if args.config:
        payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
        defaults = default_troop_training_config()
        values = {}
        for troop_type in TROOP_TYPES:
            item = payload.get(troop_type, {})
            fallback = defaults.for_type(troop_type)
            quantity_mode = str(item.get("quantity_mode", fallback.quantity_mode))
            if quantity_mode == "current_max" and item.get("quantity") is not None:
                raise ValueError(f"{troop_type}: current_max cannot include a fixed quantity")
            values[troop_type] = TrainingConfig(
                enabled=item.get("enabled", fallback.enabled),
                target_tier=item.get("target_tier", fallback.target_tier),
                quantity=(None if quantity_mode == "current_max" else (int(item["quantity"]) if "quantity" in item and item["quantity"] is not None else fallback.quantity)),
                quantity_mode=quantity_mode,
                training_policy=str(item.get("training_policy", fallback.training_policy)),
                allow_resource_boxes=item.get("allow_resource_boxes", fallback.allow_resource_boxes),
            )
        return TroopTrainingConfig(**values)
    defaults = default_troop_training_config()
    values = {}
    for troop_type in TROOP_TYPES:
        fallback = defaults.for_type(troop_type)
        tier = getattr(args, f"{troop_type}_tier")
        quantity = getattr(args, f"{troop_type}_quantity")
        mode = getattr(args, f"{troop_type}_quantity_mode")
        policy = getattr(args, f"{troop_type}_policy")
        boxes = getattr(args, f"{troop_type}_allow_resource_boxes")
        enabled = getattr(args, f"{troop_type}_enabled")
        if quantity is not None and (mode == "current_max" or (mode is None and fallback.quantity_mode == "current_max")):
            raise ValueError(f"{troop_type}: current_max cannot include a fixed quantity")
        resolved_mode = fallback.quantity_mode if mode is None else mode
        resolved_quantity = None if resolved_mode == "current_max" else (fallback.quantity if quantity is None else quantity)
        values[troop_type] = TrainingConfig(
            enabled=fallback.enabled if enabled is None else enabled,
            target_tier=fallback.target_tier if tier is None else tier,
            quantity=resolved_quantity,
            quantity_mode=resolved_mode,
            training_policy=fallback.training_policy if policy is None else policy,
            allow_resource_boxes=fallback.allow_resource_boxes if boxes is None else boxes,
        )
    return TroopTrainingConfig(**values)


def _retain_route_result(runtime: NativeRuntimePort, result: object) -> None:
    """Retain the concise machine-readable route result beside native captures."""

    path = Path(runtime.session) / "troop-training-result.json"
    path.write_text(json.dumps(asdict(result), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--reset-identity", required=True)
    parser.add_argument("--config", type=Path)
    for troop_type in TROOP_TYPES:
        parser.add_argument(f"--{troop_type}-enabled", action=argparse.BooleanOptionalAction, default=None)
        parser.add_argument(f"--{troop_type}-tier", type=int)
        parser.add_argument(f"--{troop_type}-quantity", type=int, default=None)
        parser.add_argument(f"--{troop_type}-quantity-mode", choices=("fixed", "current_max"), default=None)
        parser.add_argument(f"--{troop_type}-policy", choices=("once_daily", "continuous", "disabled"), default=None)
        parser.add_argument(
            f"--{troop_type}-allow-resource-boxes",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=f"allow exact Auto Use resource-box confirmation for {troop_type} only (default: false)",
        )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm the exact local BlueStacks target non-interactively")
    parser.add_argument(
        "--entry-only",
        "--navigation-only",
        dest="entry_only",
        action="store_true",
        help="navigate to the selected facility, recognize its radial Train control, then Back to canonical Home without tapping Train",
    )
    parser.add_argument("--home-atlas", type=Path, default=DEFAULT_HOME_ATLAS)
    parser.add_argument("--maximum-home-pans", type=int, default=4)
    parser.add_argument("--home-pan-settle-seconds", type=float, default=1.0)
    parser.add_argument(
        "--reconcile-unresolved-session",
        type=Path,
        help="reconcile one prior unresolved Train from a fresh live queue; no consequential input is available in this mode",
    )
    parser.add_argument(
        "--reconcile-forbidden-resource-popup-session",
        type=Path,
        help="cancel and reconcile one exact Auto Use resource-box successor; Train is never retried",
    )
    parser.add_argument(
        "--reconcile-resource-box-acquisition-session",
        type=Path,
        help="reconcile exact resource-box use that returned queue-empty; issues no input and never retries Train",
    )
    parser.add_argument(
        "--return-home-only",
        action="store_true",
        help="close a positively recognized training/radial surface with native Back and verify Home/Base",
    )
    parser.add_argument(
        "--recovery-active-queue",
        action="store_true",
        help="for pnsctl recovery only: require a fresh exact active queue before safe Home return",
    )
    parser.add_argument(
        "--recovery-training-screen",
        action="store_true",
        help="for pnsctl recovery only: permit a fresh recognized queue-empty training screen before safe Home return",
    )
    parser.add_argument("--radial-troop-type", choices=TROOP_TYPES, default="shooter")
    parser.add_argument("--post-input-delay", type=float, default=1.0)
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/troop-training-integrated"))
    args = parser.parse_args(argv)
    if args.execute and not args.yes:
        parser.error("--execute requires --yes")
    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="troop-training",
        execute=args.execute,
    )
    runtime.frame_max_age_seconds = TROOP_TRAINING_FRAME_MAX_AGE_SECONDS
    config = _load_config(args)
    config.validate()
    if args.return_home_only:
        result = TroopTrainingReturnHomeRoute(
            runtime,
            post_input_delay=args.post_input_delay,
            radial_troop_type=args.radial_troop_type,
            atlas_path=args.home_atlas,
            require_active_queue=args.recovery_active_queue,
            allow_queue_empty_training=args.recovery_training_screen,
        ).run()
        _retain_route_result(runtime, result)
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0 if result.status == "completed" else 3
    result = TroopTrainingIntegratedRoute(
        runtime,
        config=config,
        reset_identity=args.reset_identity,
        post_input_delay=args.post_input_delay,
        entry_only=args.entry_only,
        atlas_path=args.home_atlas,
        maximum_home_pans=args.maximum_home_pans,
        home_pan_settle_seconds=args.home_pan_settle_seconds,
    ).run()
    _retain_route_result(runtime, result)
    print(json.dumps(asdict(result), sort_keys=True, default=str))
    return 0 if result.status in {"completed", "dry-run"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
