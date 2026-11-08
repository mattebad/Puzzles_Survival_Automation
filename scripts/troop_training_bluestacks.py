"""Canonical native BlueStacks driver for the fixed Troop Training service route."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
import time
from typing import Any, Mapping

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safe_action_core import (
    ActionClass,
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    TransportResult,
)
from automation_service.commander_talents import ensure_commander_talent_preset
from automation_service.troop_training import (
    FLOW_ID,
    MAX_ACTIONS,
    MAX_INPUTS,
    PROFILE_ID,
    PRODUCT_ID,
    PRODUCT_REVISION,
    TrainingActionHistoryError,
    derive_training_action_state,
    make_training_claim_action_key,
    make_training_start_action_key,
)
from scripts.commander_talents_bluestacks import (
    COMMANDER_TALENT,
    HOME as TALENT_HOME,
    PROFILE as TALENT_PROFILE,
    TALENT_MEMORY,
    _recognized_page,
    recognize_commander_talent_page,
    run_commander_talent_preset,
)
from scripts.bluestacks_native_runtime import NativeRuntimePort
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
from scripts.startup_normalization import is_clean_home_frame
from tasks.home_atlas_vision import BLUESTACKS_PLATFORM, BLUESTACKS_PROFILE_ID, BlueStacksHomeLocalizer, bind_visible_building, frame_digest
from tasks.home_context import HomeReadyObservation
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity, resource_fixed_runtime_binding
from tasks.troop_training import (
    FACILITY_BY_TYPE,
    RESOURCE_NAMES,
    TROOP_TYPES,
    TrainingController,
    TroopTrainingConfig,
    TrainingScreenObservation,
    all_base_resources_sufficient,
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
    recognize_exit_dialog,
    recognize_home,
    recognize_radial_menu,
    recognize_training_speedup,
    recognize_training,
    recognize_training_with_targets,
)


DEFAULT_HOME_ATLAS = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"


class _TroopTrainingInputBudgetRuntime:
    """Track route navigation in the borrowed session and reserve Home input."""

    _INPUT_METHODS = frozenset(
        {"back", "clear_numeric_text", "press_key", "swipe", "tap", "type_text"}
    )

    def __init__(self, runtime, *, max_inputs: int, session=None, checkpoint=None) -> None:
        self._runtime = runtime
        self._max_inputs = int(max_inputs)
        self._session = session
        self._checkpoint = checkpoint

    def __getattr__(self, name):
        value = getattr(self._runtime, name)
        if name not in self._INPUT_METHODS or not callable(value):
            return value

        def bounded_input(*args, **kwargs):
            current = getattr(self._runtime, "input_count", None)
            if type(current) is not int:
                raise RuntimeError("troop-training native input count is unavailable")
            action_key = str(kwargs.get("action_key", ""))
            returning_home = name == "back" and "return-home" in action_key
            expected_talent_page = kwargs.pop("expected_talent_page", None)
            if expected_talent_page is not None and (
                not returning_home
                or expected_talent_page not in {TALENT_MEMORY, COMMANDER_TALENT, TALENT_PROFILE}
            ):
                raise ValueError("expected talent page requires an owned preset Back transition")
            limit = self._max_inputs if returning_home else self._max_inputs - 1
            if current >= limit:
                raise RuntimeError(
                    "troop-training input budget exhausted"
                    if returning_home
                    else "troop-training input budget reserved for Home"
                )
            if self._session is None:
                return value(*args, **kwargs)
            if not args or not callable(getattr(self._session, "run_action", None)):
                raise RuntimeError("troop-training navigation requires the borrowed native session")
            source = args[0]
            label = action_key or f"troop-training-navigation:{name}:{source.sha256}"

            def authorize(before):
                if callable(self._checkpoint):
                    self._checkpoint()
                if before.sha256 != source.sha256:
                    if expected_talent_page is None:
                        raise RuntimeError("troop-training navigation frame changed before input")
                    # Background animation is not a context change. Rebind only
                    # these owned Back transitions to the fresh, exact page.
                    observed = recognize_commander_talent_page(before, required_preset="Training")
                    if not observed.recognized or observed.page != expected_talent_page:
                        raise RuntimeError("commander-talent page changed before Back")

            def dispatch(before):
                value(before, *args[1:], **kwargs)

            self._session.run_action(
                action_class="navigation",
                label=label,
                capture=self._runtime.capture,
                dispatch=dispatch,
                recognize=lambda _after: "navigation_transport_observed",
                authorize=authorize,
                target_roi=kwargs.get("target_roi"),
                consequence_class="navigation_only",
            )
            return None

        return bounded_input




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
    """Prove a safe canonical Home surface without requiring facility labels.

    Mapped-building geometry is the entry authority; facility label OCR is not a
    stable Home predicate because panning can clip labels at the screen edge.
    The recovery contract instead requires the native HUD semantic, no recognized
    training/modal surface, and a same-frame fully-zoomed-out Atlas match.
    Non-array frames are accepted only for unit-test doubles that already provide
    a positive Home observation; native runtime frames always take the strict
    HUD/negative-surface path below.
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
    final_home_recognized: bool
    entry_navigation: dict[str, object]
    session: str
    resolved_config: dict[str, object] = field(default_factory=dict)
    training_dispatch_count: int = 0
    training_start_transport_calls: int = 0
    claim_dispatch_count: int = 0
    resource_box_dispatch_count: int = 0
    warehouse_dispatch_count: int = 0
    committed_action_count: int = 0
    effect_reconciliation_required: bool = False
    identical_retry_denied: bool = False
    terminal_home_verified: bool = False
    saved_training_preset_verified: bool = False
    remaining_eligible_variants: tuple[str, ...] = ()
    next_due_utc: float | None = None



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

def run_troop_training_home_recovery(
    runtime: NativeRuntimePort,
    *,
    session,
    checkpoint,
    max_inputs: int,
) -> Mapping[str, object]:
    """Run only the retained native return-home route under a bounded session."""

    if type(max_inputs) is not int or not 1 <= max_inputs <= MAX_INPUTS:
        raise ValueError("Training recovery input budget is outside the canonical route limit")
    if getattr(runtime, "execute", False) is not True:
        raise RuntimeError("Training Home recovery requires the authorized native runtime")
    if not callable(checkpoint) or getattr(session, "is_active", False) is not True:
        raise RuntimeError("Training Home recovery requires an active development session")
    lock = session.runtime_input_lock
    lock.assert_held(lock.owner, lock.invocation_id)
    checkpoint()
    if type(getattr(runtime, "input_count", None)) is not int:
        raise RuntimeError("Training Home recovery runtime input accounting is unavailable")
    if runtime.input_count != 0:
        raise RuntimeError("Training Home recovery runtime must start with a fresh input budget")
    runtime.max_inputs = max_inputs
    bounded = _TroopTrainingInputBudgetRuntime(
        runtime,
        max_inputs=max_inputs,
        session=session,
        checkpoint=checkpoint,
    )
    result = TroopTrainingReturnHomeRoute(
        bounded,
        require_active_queue=True,
    ).run()
    checkpoint()
    return {
        **asdict(result),
        "input_count": runtime.input_count,
        "session_input_count": session.input_count,
        "training_execution_attempted": False,
        "training_action_resolved": False,
        "training_dispatch_count": 0,
        "controls_changed": False,
    }





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
        zoom_transport=None,
        native_context: Any | None = None,
        runtime_identity_sha256: str = "",
        prior_daily_initiations: tuple[str, ...] = (),
        queue_generations: Mapping[str, int] | None = None,
        pending_start_action_keys: Mapping[str, str] | None = None,
        pending_start_reset_ids: Mapping[str, str] | None = None,
        next_start_action_keys: Mapping[str, str] | None = None,
        blocked_start_variants: Mapping[str, str] | None = None,
        per_reset_variant_start_counts: Mapping[str, int] | None = None,
        per_reset_variant_claim_counts: Mapping[str, int] | None = None,
        preset_context: Mapping[str, object] | None = None,
    ) -> None:
        self.runtime = (
            _TroopTrainingInputBudgetRuntime(
                runtime,
                max_inputs=(
                    native_context.max_inputs
                    if native_context is not None and type(native_context.max_inputs) is int
                    else MAX_INPUTS
                ),
                session=native_context.session,
                checkpoint=native_context.checkpoint,
            )
            if native_context is not None
            else runtime
        )
        self.config = config
        self.reset_identity = reset_identity
        self.post_input_delay = post_input_delay
        self.max_tier_swipes = max_tier_swipes
        self.entry_only = entry_only
        self.atlas_path = atlas_path
        self.maximum_home_pans = maximum_home_pans
        self.home_pan_settle_seconds = home_pan_settle_seconds
        self.zoom_transport = zoom_transport
        self.native_context = native_context
        self.runtime_identity_sha256 = runtime_identity_sha256
        self.pending_start_action_keys = dict(pending_start_action_keys or {})
        self.pending_start_reset_ids = dict(pending_start_reset_ids or {})
        self.start_action_keys = dict(next_start_action_keys or {})
        self.blocked_start_variants = dict(blocked_start_variants or {})
        self.per_reset_variant_start_counts = {
            troop_type: int((per_reset_variant_start_counts or {}).get(troop_type, 0))
            for troop_type in TROOP_TYPES
        }
        self.per_reset_variant_claim_counts = {
            troop_type: int((per_reset_variant_claim_counts or {}).get(troop_type, 0))
            for troop_type in TROOP_TYPES
        }
        self.preset_context = dict(preset_context or {})
        self.controller = TroopTrainingRuntimeController(
            config,
            reset_identity=reset_identity,
            prior_daily_initiations=prior_daily_initiations,
            queue_generations=queue_generations,
            pending_start_action_keys=pending_start_action_keys,
        )
        self.actions_completed = 0
        self.training_start_transport_calls = 0
        self.claim_dispatch_count = 0
        self.resource_box_dispatch_count = 0
        self.warehouse_dispatch_count = 0
        self.committed_action_count = 0
        self.effect_reconciliation_required = False
        self.identical_retry_denied = False
        self.saved_training_preset_verified = False
        self.remaining_eligible_variants: list[str] = []
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
            resolved_config[troop_type]["queue_generation"] = state.queue_generation
            resolved_config[troop_type]["per_reset_variant_start_count"] = self.per_reset_variant_start_counts[troop_type]
            resolved_config[troop_type]["per_reset_variant_claim_count"] = self.per_reset_variant_claim_counts[troop_type]
            resolved_config[troop_type]["pending_start_action_key"] = self.pending_start_action_keys.get(troop_type)
            resolved_config[troop_type]["next_start_action_key"] = self.start_action_keys.get(troop_type)
        return TroopTrainingRouteResult(
            status=status,
            reason=reason,
            actions_completed=self.actions_completed,
            completed_claims=tuple(self.completed_claims),
            warehouse_approvals=tuple(self.warehouse_approvals),
            resource_box_approvals=tuple(self.resource_box_approvals),
            training=tuple(self.training),
            final_home_recognized=final_home,
            entry_navigation=self.entry_navigation,
            session=str(self.runtime.session),
            resolved_config=resolved_config,
            training_dispatch_count=(
                self.training_start_transport_calls
                + self.claim_dispatch_count
                + self.resource_box_dispatch_count
                + self.warehouse_dispatch_count
            ),
            training_start_transport_calls=self.training_start_transport_calls,
            claim_dispatch_count=self.claim_dispatch_count,
            resource_box_dispatch_count=self.resource_box_dispatch_count,
            warehouse_dispatch_count=self.warehouse_dispatch_count,
            committed_action_count=self.committed_action_count,
            effect_reconciliation_required=self.effect_reconciliation_required,
            identical_retry_denied=self.identical_retry_denied,
            terminal_home_verified=final_home,
            saved_training_preset_verified=self.saved_training_preset_verified,
            remaining_eligible_variants=tuple(self.remaining_eligible_variants),
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
            binding = bind_visible_building(immediate_before.frame, localization, building, home_is_clean=is_clean_home_frame) if localization.recognized else None
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

    def _ensure_training_preset(self) -> str | None:
        context = self.native_context
        if context is None:
            return "NATIVE_SERVICE_CONTEXT_REQUIRED"
        try:
            result = ensure_commander_talent_preset(
                context.session,
                context.runtime,
                "Training",
                checkpoint=context.checkpoint,
                runtime_input_lock=context.runtime_input_lock,
                action_store=context.action_store,
                source_generation=context.invocation_id,
                context=self.preset_context,
                native_port=run_commander_talent_preset,
                switch_approval=None,
            )
        except Exception as exc:
            return f"TRAINING_PRESET_VERIFICATION_FAILED:{type(exc).__name__}:{exc}"
        if not result.verified or result.preset_name != "Training":
            return f"TRAINING_PRESET_NOT_VERIFIED:{result.status}:{result.reason}"
        self.saved_training_preset_verified = True
        return None

    def _policy_observation(
        self,
        captured,
        *,
        target_identity: str | None,
        target_roi,
        control_class: str | None,
        consequence: str | None,
        cost_type: str | None,
        cost_amount: float | None,
        quantity: int | None,
        postcondition: str,
        source_state: str = "TROOP_TRAINING_SCREEN",
        recognized: bool = True,
        overlay_state: str = "none_observed",
    ) -> Observation:
        try:
            package = str(self.native_context.runtime.measure_foreground_package())
        except Exception:
            package = ""
        return Observation(
            frame_sha256=str(captured.sha256),
            capture_completed_monotonic=float(captured.captured_monotonic),
            runtime_profile_id=PROFILE_ID,
            width=int(captured.frame.shape[1]),
            height=int(captured.frame.shape[0]),
            valid_png=True,
            corrupt=False,
            black=False,
            source_state=source_state,
            overlay_state=overlay_state,
            target_identity=target_identity,
            target_roi=target_roi,
            recognized=recognized,
            control_class=control_class,
            consequence=consequence,
            cost_type=cost_type,
            cost_amount=cost_amount,
            quantity=quantity,
            expected_postcondition=postcondition,
            evidence_refs=(str(captured.path),),
            source_family="troop_training",
            target_isolated=target_roi is not None,
            package_foreground=package == "com.global.ztmslg",
        )

    def _execute_canonical_action(
        self,
        *,
        captured,
        target_identity: str,
        target_key: str,
        target_roi,
        action_key: str,
        semantic_action: str,
        action_kind: str,
        subject: str,
        counter_variant: str,
        action_class: ActionClass,
        control_class: str,
        consequence: str,
        postcondition: str,
        cost_type: str,
        cost_amount: int,
        action_quantity: int,
        resource_or_currency: str | None,
        maximum_cost: int,
        free_only: bool,
        semantic_preconditions: tuple[str, ...],
        before_positive,
        after_positive,
        counter_kind: str,
    ) -> dict[str, object]:
        context = self.native_context
        if context is None:
            return {"status": "blocked", "reason": "NATIVE_SERVICE_CONTEXT_REQUIRED", "transport_calls": 0}
        input_budget = context.max_inputs if type(context.max_inputs) is int else MAX_INPUTS
        runtime_input_count = getattr(context.runtime, "input_count", None)
        if type(runtime_input_count) is not int or runtime_input_count >= input_budget - 1:
            return {"status": "blocked", "reason": "TRAINING_INPUT_BUDGET_HOME_RESERVE", "transport_calls": 0}
        training_dispatch_count = (
            self.training_start_transport_calls
            + self.claim_dispatch_count
            + self.resource_box_dispatch_count
            + self.warehouse_dispatch_count
        )
        action_budget = context.max_actions if type(context.max_actions) is int else MAX_ACTIONS
        if training_dispatch_count >= action_budget:
            return {"status": "blocked", "reason": "TRAINING_CONSEQUENTIAL_ACTION_BUDGET_EXHAUSTED", "transport_calls": 0}
        observation = self._policy_observation(
            captured,
            target_identity=target_identity,
            target_roi=target_roi,
            control_class=control_class,
            consequence=consequence,
            cost_type=cost_type,
            cost_amount=cost_amount,
            quantity=action_quantity,
            postcondition=postcondition,
        )
        now = float(context.utc_clock())
        monotonic_now = float(context.monotonic_clock())
        store, session, runtime = context.action_store, context.session, context.runtime
        action_id = f"troop-training:{hashlib.sha256((action_key + context.invocation_id).encode()).hexdigest()}"
        request = PolicyRequest(
            action_id=action_id,
            action_key=action_key,
            task_id=FLOW_ID,
            task_mode="supervised_validation",
            semantic_action=semantic_action,
            expected_runtime_profile_id=PROFILE_ID,
            observation=observation,
            monotonic_now=monotonic_now,
            observation_max_age_seconds=30.0,
            dispatch_max_age_seconds=30.0,
            lease_owner=session.owner,
            lease_valid=store.lease_valid_for(session.owner, now),
            unresolved_action=store.has_action_block(),
            duplicate_action_key=store.action_key_exists(action_key),
            game_day_id=self.reset_identity,
            action_class=action_class,
            action_kind=action_kind,
            subject=subject,
            resource_or_currency=resource_or_currency,
            maximum_cost=maximum_cost,
            free_only=free_only,
            semantic_preconditions=semantic_preconditions,
            semantic_postconditions=(postcondition,),
            runtime_session_id=str(runtime.session),
        )
        policy = CentralPolicy(frozenset({FLOW_ID}))

        post_captures: list[tuple[Any, TrainingScreenObservation, bool]] = []
        dispatch_counts: list[int] = []

        def record_dispatch(count: int) -> None:
            if count <= 0:
                return
            dispatch_counts.append(count)
            self.actions_completed += count
            if counter_kind == "start":
                self.training_start_transport_calls += count
                self.per_reset_variant_start_counts[counter_variant] += count
            elif counter_kind == "claim":
                self.claim_dispatch_count += count
                self.per_reset_variant_claim_counts[counter_variant] += count
            else:
                raise ValueError("unknown troop-training consequential counter")

        def transport(_intent):
            runtime_before = getattr(runtime, "input_count", None)
            session_before = getattr(session, "input_count", None)
            if type(runtime_before) is not int or type(session_before) is not int:
                raise RuntimeError("native input accounting is unavailable before consequential dispatch")
            source_returned = False

            def capture_for_action(label):
                nonlocal source_returned
                if not source_returned:
                    source_returned = True
                    return captured
                return runtime.capture(label)

            def authorize(before):
                context.checkpoint()
                context.validate_identity()
                if before.sha256 != captured.sha256:
                    raise RuntimeError("training target frame changed before consequential input")
                fresh = recognize_training_with_targets(before.frame)
                if (
                    not fresh.observation.recognized
                    or fresh.target(target_key) != target_roi
                    or not before_positive(fresh.observation)
                ):
                    raise RuntimeError("training source facts or target changed before consequential input")

            def dispatch(before):
                if counter_kind == "start":
                    dispatch_decision = self.controller.dispatch_started(
                        counter_variant,
                        action_key,
                    )
                    if dispatch_decision.action != "await_postcondition":
                        raise RuntimeError("training controller rejected its preauthorized start")
                runtime.tap(
                    before,
                    target_identity=target_identity,
                    target_roi=target_roi,
                    action_key=action_key,
                    action_class=action_kind,
                    consequential=True,
                )

            def recognize(after):
                fresh = recognize_training_with_targets(after.frame)
                shape_ok = (
                    getattr(session, "input_count", None) - session_before == 1
                    and getattr(runtime, "input_count", None) - runtime_before == 1
                )
                positive = bool(shape_ok and after_positive(fresh.observation))
                post_captures.append((after, fresh.observation, positive))
                return postcondition if positive else "unknown"

            def settled_successor():
                if context.settle_seconds > 0:
                    time.sleep(float(context.settle_seconds))
                context.checkpoint()
                return runtime.capture(f"{counter_kind}-post-settled")

            try:
                session.run_action(
                    action_class=action_kind,
                    label=f"troop-training-{counter_kind}-{subject}",
                    capture=capture_for_action,
                    dispatch=dispatch,
                    recognize=recognize,
                    authorize=authorize,
                    target_roi=target_roi,
                    consequence_class=consequence,
                    settled_successor=settled_successor,
                )
            except Exception as exc:
                runtime_delta = int(getattr(runtime, "input_count", runtime_before)) - runtime_before
                session_delta = int(getattr(session, "input_count", session_before)) - session_before
                record_dispatch(max(runtime_delta, session_delta))
                return TransportResult(
                    max(runtime_delta, session_delta) > 0,
                    f"TROOP_TRAINING_TRANSPORT_{type(exc).__name__}",
                )
            runtime_delta = int(getattr(runtime, "input_count", runtime_before)) - runtime_before
            session_delta = int(getattr(session, "input_count", session_before)) - session_before
            actual_count = max(runtime_delta, session_delta)
            record_dispatch(actual_count)
            if runtime_delta != 1 or session_delta != 1:
                return TransportResult(actual_count > 0, "TROOP_TRAINING_INPUT_ACCOUNTING_MISMATCH")
            return TransportResult(True, "TROOP_TRAINING_CONSEQUENTIAL_INPUT_SENT")

        immediate: dict[str, Observation] = {}

        def recapture():
            nonlocal captured
            if "observation" in immediate:
                return immediate["observation"]
            context.checkpoint()
            context.validate_identity()
            fresh_capture = runtime.capture(f"troop-training-{counter_kind}-pre-dispatch")
            fresh = recognize_training_with_targets(fresh_capture.frame)
            if (
                not fresh.observation.recognized
                or fresh.target(target_key) != target_roi
                or not before_positive(fresh.observation)
            ):
                raise RuntimeError("training immediate facts or target changed before dispatch")
            captured = fresh_capture
            immediate["observation"] = self._policy_observation(
                fresh_capture,
                target_identity=target_identity,
                target_roi=target_roi,
                control_class=control_class,
                consequence=consequence,
                cost_type=cost_type,
                cost_amount=cost_amount,
                quantity=action_quantity,
                postcondition=postcondition,
            )
            return immediate["observation"]

        def post_observe():
            if not post_captures:
                return ()
            post_capture, _semantic, positive = post_captures[-1]
            return (
                self._policy_observation(
                    post_capture,
                    target_identity=None,
                    target_roi=None,
                    control_class=None,
                    consequence=None,
                    cost_type=None,
                    cost_amount=None,
                    quantity=None,
                    postcondition=postcondition,
                    source_state=postcondition if positive else "UNKNOWN",
                    recognized=positive,
                    overlay_state="none_observed" if positive else "unknown",
                ),
            )

        def reconcile(_intent, observed):
            return bool(
                post_captures
                and observed.frame_sha256 == post_captures[-1][0].sha256
                and observed.source_state == postcondition
                and post_captures[-1][2]
            )

        capability_observation = recapture()
        issue_time = float(context.utc_clock())
        capability_request = replace(
            request,
            observation=capability_observation,
            monotonic_now=float(context.monotonic_clock()),
            lease_valid=store.lease_valid_for(session.owner, issue_time),
            unresolved_action=store.has_action_block(),
            duplicate_action_key=store.action_key_exists(action_key),
            policy_phase="pre_dispatch",
        )
        issued = policy.issue_capability(capability_request)
        store.audit(FLOW_ID, "capability_issued", issue_time, issued.audit, action_id)
        if not issued.authorized or issued.capability is None:
            if issued.reason_code == "DUPLICATE_ACTION_KEY" or store.action_key_exists(action_key):
                self.identical_retry_denied = True
            return {
                "status": "blocked",
                "reason": issued.reason_code,
                "action_key": action_key,
                "transport_calls": 0,
            }

        execution = SafeActionExecutor(
            store,
            policy,
            session.owner,
            context.monotonic_clock,
            transport,
            recapture,
            post_observe,
            reconcile,
            wall_clock=context.utc_clock,
            max_pre_dispatch_attempts=1,
        ).execute(request, issued.capability)
        actual_count = sum(dispatch_counts)
        if execution.status is ActionStatus.CONFIRMED and actual_count == 1:
            self.committed_action_count += 1
        elif execution.status is ActionStatus.UNRESOLVED or actual_count:
            self.effect_reconciliation_required = True
            self.identical_retry_denied = True
        row = store.get_action_by_key(action_key)
        if row is not None and row.get("final_status") == "cancelled":
            self.identical_retry_denied = True
        return {
            "status": (
                "confirmed"
                if execution.status is ActionStatus.CONFIRMED
                else "unresolved"
                if execution.status is ActionStatus.UNRESOLVED
                else "blocked"
            ),
            "reason": execution.reason,
            "action_key": action_key,
            "journal_status": row.get("final_status") if row else None,
            "transport_calls": actual_count,
            "executor_transport_calls": execution.transport_calls,
            "effect_reconciliation_required": execution.status is ActionStatus.UNRESOLVED,
            "successor_sha256": post_captures[-1][0].sha256 if post_captures else None,
            "successor_capture": post_captures[-1][0] if post_captures else None,
            "successor_observation": post_captures[-1][1] if post_captures else None,
        }

    def _navigation_tap(self, captured, *, identity: str, roi, action_key: str) -> None:
        self.runtime.tap(captured, target_identity=identity, target_roi=roi, action_key=action_key)
        self.actions_completed += 1
        self._wait()

    def _claim_completed_tab(self, captured, observation: TrainingScreenObservation):
        troop_type = observation.troop_type
        if troop_type is None or not observation.completion_ready:
            return captured, observation, None
        start_action_key = self.pending_start_action_keys.get(troop_type)
        start_reset_id = self.pending_start_reset_ids.get(troop_type)
        if not start_action_key or not start_reset_id:
            return None, None, "completed legacy/unknown queue requires manual reconciliation; no start row may be fabricated"
        bound = replace(observation, completion_batch_id=start_action_key)
        recognition = recognize_training_with_targets(captured.frame)
        target = recognition.target(f"tab:{troop_type}")
        config = self.config.for_type(troop_type)
        state = self.controller.semantic.states[troop_type]
        quantity = observation.selected_quantity
        batch_quantity = observation.queue_quantity
        if (
            target is None
            or observation.facility_identity != FACILITY_BY_TYPE[troop_type]
            or observation.queue_troop_type != troop_type
            or observation.queue_tier != config.target_tier
            or type(quantity) is not int
            or type(batch_quantity) is not int
            or batch_quantity != quantity
            or type(observation.quantity_maximum) is not int
            or observation.quantity_maximum <= 0
            or self.controller.semantic.plan_claim(bound, action_key=make_training_claim_action_key(start_action_key))
            != "authorize_claim"
        ):
            return None, None, "completed troop claim identity or quantity is not positively authorizeable"
        action_key = make_training_claim_action_key(start_action_key)
        facility = FACILITY_BY_TYPE[troop_type].casefold().replace(" ", "_")
        configured = "current_max" if config.quantity_mode == "current_max" else str(config.quantity)
        preconditions = (
            f"troop_training_product={PRODUCT_ID}",
            f"troop_training_product_revision={PRODUCT_REVISION}",
            "approved_profile=true",
            f"runtime_scope={resource_fixed_runtime_binding().runtime_scope}",
            f"account_id={self.native_context.identity.account_id}",
            f"server_id={self.native_context.identity.server_id}",
            f"runtime_identity_sha256={self.runtime_identity_sha256}",
            f"variant={troop_type}",
            f"facility_identity={facility}",
            f"troop_type={troop_type}",
            f"tier={config.target_tier}",
            f"quantity_mode={config.quantity_mode}",
            f"configured_quantity={configured}",
            f"selected_quantity={quantity}",
            "completed_batch_ready=true",
            f"completed_batch_id={start_action_key}",
            f"confirmed_start_action_key={start_action_key}",
            f"confirmed_start_reset_id={start_reset_id}",
            f"completed_batch_troop_type={troop_type}",
            f"completed_batch_tier={observation.queue_tier}",
            f"completed_batch_quantity={batch_quantity}",
            "queue_state=positively_completed",
            f"queue_generation={state.queue_generation}",
            f"per_reset_variant_start_count={self.per_reset_variant_start_counts[troop_type]}",
            f"per_reset_variant_claim_count={self.per_reset_variant_claim_counts[troop_type]}",
            f"reset_id={self.reset_identity}",
            "overlay=none",
            "forbidden_controls=none",
        )
        postcondition = f"TROOP_TRAINING_BATCH_CLAIMED:{troop_type}:{start_action_key}"

        def before_positive(fresh):
            return bool(
                fresh.troop_type == troop_type
                and fresh.facility_identity == FACILITY_BY_TYPE[troop_type]
                and fresh.overlay_state == "none"
                and fresh.completion_ready
                and fresh.queue_troop_type == troop_type
                and fresh.queue_tier == config.target_tier
                and fresh.queue_quantity == batch_quantity
                and fresh.selected_tier == config.target_tier
                and fresh.selected_quantity == quantity
                and not fresh.premium_popup
                and not fresh.forbidden_controls
            )

        def after_positive(fresh):
            return bool(
                fresh.recognized
                and fresh.troop_type == troop_type
                and fresh.facility_identity == FACILITY_BY_TYPE[troop_type]
                and fresh.overlay_state == "none"
                and not fresh.completion_ready
                and fresh.selected_tier == config.target_tier
                and fresh.selected_quantity == quantity
                and not fresh.premium_popup
                and not fresh.forbidden_controls
            )

        result = self._execute_canonical_action(
            captured=captured,
            target_identity=f"troop_training:completed_batch_claim:{troop_type}",
            target_key=f"tab:{troop_type}",
            target_roi=target,
            action_key=action_key,
            semantic_action="TROOP_TRAINING_COMPLETED_BATCH_CLAIM",
            action_kind="TROOP_TRAINING_COMPLETED_BATCH_CLAIM",
            subject="TROOP_TRAINING_COMPLETED_BATCH_CLAIM",
            counter_variant=troop_type,
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
            control_class=f"tab:{troop_type}:claim-completed",
            consequence="claim_zero_cost_reward",
            postcondition=postcondition,
            cost_type="none",
            cost_amount=0,
            action_quantity=1,
            resource_or_currency=None,
            maximum_cost=0,
            free_only=True,
            semantic_preconditions=preconditions,
            before_positive=before_positive,
            after_positive=after_positive,
            counter_kind="claim",
        )
        if result["status"] != "confirmed":
            if result["status"] == "unresolved":
                self.effect_reconciliation_required = True
                self.identical_retry_denied = True
                return None, None, f"completed troop claim unresolved: {result['reason']}"
            return captured, bound, f"completed troop claim blocked: {result['reason']}"
        post_capture = result.get("successor_capture")
        post = result.get("successor_observation")
        if (
            post_capture is None
            or not isinstance(post, TrainingScreenObservation)
            or not self.controller.semantic.reconcile_claim(bound, post, action_key=action_key)
        ):
            self.effect_reconciliation_required = True
            self.identical_retry_denied = True
            return None, None, "completed troop claim successor did not reconcile to the same persisted batch"
        recovered = derive_training_action_state(
            self.native_context.action_store.list_actions_for_task(FLOW_ID),
            runtime_scope=resource_fixed_runtime_binding().runtime_scope,
            account_id=self.native_context.identity.account_id,
            server_id=self.native_context.identity.server_id,
            game_day_id=self.reset_identity,
        )
        if (
            recovered.pending_start_action_keys.get(troop_type) is not None
            or recovered.queue_generations[troop_type] != state.queue_generation
        ):
            self.effect_reconciliation_required = True
            self.identical_retry_denied = True
            return None, None, "confirmed troop claim is not reflected in canonical queue history"
        next_key = recovered.next_start_action_keys.get(troop_type)
        if next_key is not None:
            self.start_action_keys[troop_type] = next_key
        elif troop_type in recovered.blocked_start_variants:
            self.blocked_start_variants[troop_type] = recovered.blocked_start_variants[troop_type]
        self.pending_start_action_keys.pop(troop_type, None)
        self.pending_start_reset_ids.pop(troop_type, None)
        self.controller.semantic.pending_start_action_keys.pop(troop_type, None)
        self.completed_claims.append(
            {
                "troop_type": troop_type,
                "action_key": action_key,
                "confirmed_start_action_key": start_action_key,
                "confirmed_start_reset_id": start_reset_id,
                "source_frame_hash": captured.sha256,
                "post_frame_hash": post_capture.sha256,
                "batch_identity": start_action_key,
            }
        )
        self.training.append(
            {
                "troop_type": troop_type,
                "facility_identity": state.facility_identity,
                "selected_tier": observation.selected_tier,
                "quantity": observation.selected_quantity,
                "configured_quantity": state.configured_quantity,
                "quantity_mode": state.quantity_mode,
                "quantity_maximum": observation.quantity_maximum,
                "maximum_equality_proven": state.quantity_mode != "current_max"
                or observation.selected_quantity == observation.quantity_maximum,
                "queue_label": observation.queue_label,
                "queue_troop_type": observation.queue_troop_type,
                "queue_tier": observation.queue_tier,
                "queue_quantity": observation.queue_quantity,
                "queue_state": "completed_claimed",
                "completion_policy": "canonical_confirmed_batch_claim",
                "batch_identity": start_action_key,
                "action_key": action_key,
                "daily_initiation_state": state.daily_initiation_state,
                "reset_identity": self.reset_identity,
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
        # The editor may retain a stale numeric value; clear the full observed maximum width.
        # Then enter the exact authorized quantity.
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
        context = self.native_context
        if context is None:
            return None, None, "canonical native service context is required for Train"
        captured = context.runtime.capture(f"{troop_type}-train-immediate-before")
        recognition = recognize_training_with_targets(captured.frame)
        observation = recognition.observation
        config = self.config.for_type(troop_type)
        state = self.controller.semantic.states[troop_type]
        if (
            not observation.recognized
            or observation.troop_type != troop_type
            or observation.facility_identity != FACILITY_BY_TYPE[troop_type]
            or observation.overlay_state != "none"
            or observation.queue_active
            or observation.completion_ready
            or observation.premium_popup
            or observation.forbidden_controls
        ):
            return None, None, "fresh exact queue-empty training source is not recognized"
        plan = self.controller.semantic.plan_training(observation, troop_type)
        if plan in {
            "defer_resource_shortage_effect_authority_unavailable",
            "defer_warehouse_confirmation_authority_unavailable",
            "defer_resource_shortage_resource_boxes_disabled",
        }:
            decision = self.controller.observe_training(observation, troop_type)
            if decision.action != "defer":
                return None, None, decision.reason
            return captured, observation, plan
        if plan != "authorize_normal_train":
            return None, None, plan
        if not all_base_resources_sufficient(observation.resources):
            decision = self.controller.observe_training(observation, troop_type)
            if decision.action == "defer":
                return captured, observation, decision.reason
            return None, None, decision.reason
        if observation.normal_train_target is None or recognition.target("train") != observation.normal_train_target:
            return None, None, "normal Train target is not positively bound on the fresh frame"
        quantity = self.controller.semantic.resolved_quantity(observation, troop_type)
        if (
            type(quantity) is not int
            or type(observation.selected_quantity) is not int
            or observation.selected_quantity != quantity
            or type(observation.quantity_maximum) is not int
            or observation.quantity_maximum <= 0
        ):
            return None, None, "numeric current quantity and capacity do not match the fixed variant"
        if config.quantity_mode == "current_max" and quantity != observation.quantity_maximum:
            return None, None, "current numeric maximum is not selected exactly"
        if config.quantity_mode == "fixed" and (
            config.quantity != 250 or quantity != 250 or observation.quantity_maximum < 250
        ):
            return None, None, "fixed daily quantity is not exactly 250 within the current numeric capacity"
        action_key = self.start_action_keys.get(troop_type)
        candidate_generation = state.queue_generation + 1
        if not action_key:
            if troop_type in self.blocked_start_variants:
                self.identical_retry_denied = True
                return None, None, self.blocked_start_variants[troop_type]
            return None, None, "canonical next queue-generation action key is missing"
        try:
            expected_action_key = make_training_start_action_key(
                self.runtime_identity_sha256,
                self.reset_identity,
                troop_type,
                candidate_generation,
            )
        except ValueError:
            return None, None, "canonical start-key identity is incomplete"
        if action_key != expected_action_key:
            return None, None, "canonical start key does not match the exact identity/reset/variant/global generation"
        resources = observation.resources_by_name()
        if set(resources) != set(RESOURCE_NAMES) or len(observation.resources) != len(RESOURCE_NAMES):
            return None, None, "exact four-resource cost vector is unresolved"
        resource_tokens: list[str] = []
        required_costs: list[int] = []
        frozen_resources: dict[str, tuple[int, int]] = {}
        for name in RESOURCE_NAMES:
            reading = resources[name]
            if type(reading.held) is not int or type(reading.required) is not int or reading.held < reading.required:
                return None, None, f"resource.{name} held/required amount is missing or insufficient"
            frozen_resources[name] = (reading.held, reading.required)
            required_costs.append(reading.required)
            resource_tokens.extend(
                (
                    f"resource.{name}.held={reading.held}",
                    f"resource.{name}.required={reading.required}",
                )
            )
        configured = "current_max" if config.quantity_mode == "current_max" else str(config.quantity)
        facility = FACILITY_BY_TYPE[troop_type].casefold().replace(" ", "_")
        preconditions = (
            f"troop_training_product={PRODUCT_ID}",
            f"troop_training_product_revision={PRODUCT_REVISION}",
            f"runtime_scope={resource_fixed_runtime_binding().runtime_scope}",
            f"account_id={context.identity.account_id}",
            f"server_id={context.identity.server_id}",
            f"runtime_identity_sha256={self.runtime_identity_sha256}",
            f"game_day_id={self.reset_identity}",
            "approved_profile=true",
            f"variant={troop_type}",
            f"facility_identity={facility}",
            f"troop_type={troop_type}",
            f"tier={config.target_tier}",
            f"quantity_mode={config.quantity_mode}",
            f"configured_quantity={configured}",
            f"selected_quantity={quantity}",
            f"quantity_maximum={observation.quantity_maximum}",
            f"training_policy={config.training_policy}",
            f"allow_resource_boxes={str(config.allow_resource_boxes).lower()}",
            "queue_state=positively_empty",
            f"queue_generation={candidate_generation}",
            f"per_reset_variant_start_count={self.per_reset_variant_start_counts[troop_type]}",
            "saved_commander_talent_preset=Training",
            "saved_commander_talent_preset_verified=true",
            *resource_tokens,
            "forbidden_controls=none",
            "overlay=none",
        )
        if len(preconditions) != 33 or not self.runtime_identity_sha256:
            return None, None, "exact training policy preconditions are incomplete"
        preset_error = self._ensure_training_preset()
        if preset_error is not None:
            return None, None, preset_error
        decision = self.controller.observe_training(observation, troop_type)
        if decision.action != "start_training":
            return None, None, decision.reason
        dispatched_at = datetime.fromtimestamp(float(context.utc_clock()), timezone.utc)
        postcondition = (
            f"active_queue_confirmed:{troop_type}:{config.target_tier}:"
            f"{quantity}:positive_current_timer"
        )

        def before_positive(fresh):
            fresh_resources = fresh.resources_by_name()
            return bool(
                fresh.troop_type == troop_type
                and fresh.facility_identity == FACILITY_BY_TYPE[troop_type]
                and fresh.overlay_state == "none"
                and not fresh.queue_active
                and not fresh.completion_ready
                and fresh.queue_label is None
                and fresh.queue_troop_type is None
                and fresh.queue_tier is None
                and fresh.queue_quantity is None
                and fresh.diagnostics.get("duration_source") not in {"queue_band", "queue_timer_band"}
                and fresh.training_duration_seconds == observation.training_duration_seconds
                and fresh.selected_tier == config.target_tier
                and fresh.selected_quantity == quantity
                and fresh.quantity_maximum == observation.quantity_maximum
                and set(fresh_resources) == set(RESOURCE_NAMES)
                and all(
                    type(fresh_resources[name].held) is int
                    and type(fresh_resources[name].required) is int
                    and (fresh_resources[name].held, fresh_resources[name].required) == frozen_resources[name]
                    for name in RESOURCE_NAMES
                )
                and not fresh.premium_popup
                and not fresh.forbidden_controls
            )

        def after_positive(fresh):
            return bool(
                fresh.recognized
                and fresh.troop_type == troop_type
                and fresh.facility_identity == FACILITY_BY_TYPE[troop_type]
                and fresh.overlay_state == "none"
                and fresh.queue_active
                and fresh.queue_label
                and fresh.queue_troop_type == troop_type
                and fresh.queue_tier == config.target_tier
                and fresh.queue_quantity == quantity
                and fresh.selected_tier == config.target_tier
                and fresh.selected_quantity == quantity
                and type(fresh.quantity_maximum) is int
                and fresh.quantity_maximum > 0
                and (config.quantity_mode != "current_max" or fresh.quantity_maximum == quantity)
                and type(fresh.training_duration_seconds) is int
                and fresh.training_duration_seconds > 0
                and fresh.diagnostics.get("duration_source") == "queue_band"
                and fresh.diagnostics.get("queue_spatially_associated") is True
                and not fresh.premium_popup
                and not fresh.forbidden_controls
            )

        result = self._execute_canonical_action(
            captured=captured,
            target_identity=f"troop_training:normal_train:{troop_type}",
            target_key="train",
            target_roi=observation.normal_train_target,
            action_key=action_key,
            semantic_action="TROOP_TRAINING_START",
            action_kind="troop_training_start",
            subject=troop_type,
            counter_variant=troop_type,
            action_class=ActionClass.SPEND_OR_STRATEGIC,
            control_class="TRAIN",
            consequence="troop_training_start",
            postcondition=postcondition,
            cost_type="ordinary_game_resources",
            cost_amount=sum(required_costs),
            action_quantity=quantity,
            resource_or_currency="food+wood+steel+gas",
            maximum_cost=sum(required_costs),
            free_only=False,
            semantic_preconditions=preconditions,
            before_positive=before_positive,
            after_positive=after_positive,
            counter_kind="start",
        )
        if result["status"] != "confirmed":
            if result["status"] == "unresolved":
                self.effect_reconciliation_required = True
                self.identical_retry_denied = True
                return None, None, f"training start unresolved: {result['reason']}"
            return captured, observation, f"training start blocked: {result['reason']}"
        post_capture = result.get("successor_capture")
        post = result.get("successor_observation")
        if post_capture is None or not isinstance(post, TrainingScreenObservation):
            self.effect_reconciliation_required = True
            self.identical_retry_denied = True
            return None, None, "confirmed training action lost its positive queue successor"
        reconciled = self.controller.reconcile_started(
            troop_type,
            observation,
            post,
            action_key=action_key,
            dispatched_at=dispatched_at,
        )
        if reconciled.action != "yield":
            self.effect_reconciliation_required = True
            self.identical_retry_denied = True
            return None, None, f"canonical confirmed queue did not reconcile in controller: {reconciled.reason}"
        self.pending_start_action_keys[troop_type] = action_key
        self.pending_start_reset_ids[troop_type] = self.reset_identity
        self.controller.semantic.pending_start_action_keys[troop_type] = action_key
        self.start_action_keys.pop(troop_type, None)
        state = self.controller.semantic.states[troop_type]
        self.training.append(
            {
                "troop_type": troop_type,
                "facility_identity": state.facility_identity,
                "selected_tier": state.target_tier,
                "quantity": state.resolved_quantity,
                "configured_quantity": state.configured_quantity,
                "quantity_mode": state.quantity_mode,
                "quantity_maximum": observation.quantity_maximum,
                "maximum_equality_proven": config.quantity_mode != "current_max"
                or observation.selected_quantity == observation.quantity_maximum,
                "queue_label": post.queue_label,
                "queue_troop_type": post.queue_troop_type,
                "queue_tier": post.queue_tier,
                "queue_quantity": post.queue_quantity,
                "duration_source": post.diagnostics.get("duration_source"),
                "queue_spatially_associated": post.diagnostics.get("queue_spatially_associated") is True,
                "queue_roi": post.diagnostics.get("queue_band"),
                "resources_before": [asdict(resource) for resource in observation.resources],
                "resources_after": [asdict(resource) for resource in post.resources],
                "reset_identity": self.reset_identity,
                "action_key": action_key,
                "queue_generation": state.queue_generation,
                "source_frame_hash": captured.sha256,
                "immediate_before_frame_hash": captured.sha256,
                "immediate_post_frame_hash": post_capture.sha256,
                "displayed_training_duration_seconds": state.training_duration_seconds,
                "dispatch_timestamp": dispatched_at.isoformat(),
                "expected_completion_timestamp": (
                    state.expected_completion_timestamp.isoformat()
                    if state.expected_completion_timestamp else None
                ),
                "queue_state": state.queue_state,
                "training_policy": state.training_policy,
                "next_eligible_timestamp": (
                    state.next_eligible_timestamp.isoformat()
                    if state.next_eligible_timestamp else None
                ),
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
        self.remaining_eligible_variants = list(enabled_types)
        input_limit = (
            self.native_context.max_inputs
            if self.native_context is not None and type(self.native_context.max_inputs) is int
            else MAX_INPUTS
        )
        for index, troop_type in enumerate(enabled_types):
            if self.runtime.input_count >= input_limit - 1:
                self.remaining_eligible_variants = list(enabled_types[index:])
                return self._return_home(
                    captured,
                    status="partial",
                    reason="bounded native input budget reserved Home; remaining variants are explicitly due",
                )
            captured, observation, error = self._switch_tab(captured, observation, troop_type)
            if error:
                unresolved = self.runtime.in_flight_action is not None or self.controller.unresolved_action is not None
                return self._result("unresolved" if unresolved else "blocked", error)
            self.controller.begin_facility(troop_type, captured.sha256)
            if observation.completion_ready:
                captured, observation, error = self._claim_completed_tab(captured, observation)
                if error:
                    return self._result("blocked", f"{troop_type}: {error}")
                if self.config.for_type(troop_type).training_policy == "once_daily":
                    self.remaining_eligible_variants.remove(troop_type)
                    continue
            if observation.queue_active:
                queue_plan = self.controller.semantic.reconcile_active_queue(observation, troop_type)
                if queue_plan != "active_queue_reconciled":
                    return self._result("blocked", f"{troop_type}: {queue_plan}")
                self._record_reconciled_queue(captured, observation, troop_type)
                self.remaining_eligible_variants.remove(troop_type)
                continue
            config = self.config.for_type(troop_type)
            if (
                config.training_policy == "once_daily"
                and self.controller.semantic.states[troop_type].daily_initiation_state == "initiated"
            ):
                self.training.append(
                    {
                        "troop_type": troop_type,
                        "queue_state": "empty",
                        "daily_initiation_state": "initiated",
                        "training_policy": "once_daily",
                        "status": "already_started_this_reset",
                    }
                )
                self.remaining_eligible_variants.remove(troop_type)
                continue
            captured, observation, error = self._select_tier(captured, observation, troop_type)
            if error:
                return self._result("blocked", f"{troop_type}: {error}")
            captured, observation, error = self._set_quantity(captured, observation, troop_type)
            if error:
                return self._result("blocked", f"{troop_type}: {error}")
            captured, observation, error = self._train(captured, observation, troop_type)
            if error:
                unresolved = self.runtime.in_flight_action is not None or self.controller.unresolved_action is not None
                if unresolved:
                    self.effect_reconciliation_required = True
                    self.identical_retry_denied = True
                    return self._result("unresolved", f"{troop_type}: {error}")
                if (
                    error in {
                        "defer_resource_shortage_effect_authority_unavailable",
                        "defer_warehouse_confirmation_authority_unavailable",
                        "defer_resource_shortage_resource_boxes_disabled",
                    }
                    and captured is not None
                    and observation is not None
                    and observation.recognized
                    and not observation.queue_active
                    and not observation.completion_ready
                ):
                    self.training.append(
                        {
                            "troop_type": troop_type,
                            "queue_state": "empty",
                            "status": (
                                "deferred_warehouse_confirmation"
                                if error == "defer_warehouse_confirmation_authority_unavailable"
                                else "deferred_resource_shortage"
                            ),
                            "reason": error,
                        }
                    )
                    continue
                if (
                    error.startswith("training start blocked: TRAINING_INPUT_BUDGET_HOME_RESERVE")
                    and captured is not None
                    and observation is not None
                    and observation.recognized
                ):
                    self.remaining_eligible_variants = list(enabled_types[index:])
                    return self._return_home(
                        captured,
                        status="partial",
                        reason="bounded native input budget reserved Home; remaining variants are explicitly due",
                    )
                if captured is not None and observation is not None and observation.recognized:
                    return self._return_home(
                        captured,
                        status="blocked",
                        reason=f"{troop_type}: {error}",
                    )
                return self._result("blocked", f"{troop_type}: {error}")
            if troop_type in self.remaining_eligible_variants:
                self.remaining_eligible_variants.remove(troop_type)
        if self.remaining_eligible_variants:
            return self._return_home(
                captured,
                status="partial",
                reason="one or more independent variants remain eligible after exact resource reconciliation",
            )
        return self._return_home(captured)

    def run(self) -> TroopTrainingRouteResult:
        self.config.validate()
        target = first_enabled_entry_target(self.config)
        if target is None:
            return self._result("completed", "all troop workflows disabled; no input authorized", final_home=True)
        enabled_types = [troop_type for troop_type in TROOP_TYPES if self.config.for_type(troop_type).enabled and self.config.for_type(troop_type).training_policy != "disabled"]
        self.remaining_eligible_variants = list(enabled_types)
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
            if "troop-training input budget reserved for Home" in str(exc):
                if self.runtime.in_flight_action is None and self.controller.unresolved_action is None:
                    try:
                        budget_capture, budget_observation = self._capture_training(
                            "input-budget-partial-current-training"
                        )
                    except Exception:
                        budget_capture, budget_observation = None, None
                    if (
                        budget_capture is not None
                        and budget_observation is not None
                        and budget_observation.recognized
                        and budget_observation.overlay_state == "none"
                    ):
                        return self._return_home(
                            budget_capture,
                            status="partial",
                            reason="bounded native input budget reserved Home; remaining variants are explicitly due",
                        )
            if self.runtime.in_flight_action is not None:
                return self._result("unresolved", f"runtime failure after consequential action: {exc}")
            return self._result("blocked", f"safe route stop: {exc}")


def _training_return_to_home_after_preset(context, runtime) -> tuple[Any | None, str | None]:
    expected_next = {
        TALENT_MEMORY: COMMANDER_TALENT,
        COMMANDER_TALENT: TALENT_PROFILE,
        TALENT_PROFILE: TALENT_HOME,
    }
    for _ in range(4):
        context.checkpoint()
        captured = context.runtime.capture("training-preset-return-home-before")
        page = recognize_commander_talent_page(
            captured,
            required_preset="Training",
        )
        if not page.recognized:
            return None, "commander-talent page is not positively recognized after preset verification"
        if page.page == TALENT_HOME:
            home = recognize_home(captured.frame, reset_identity=context.identity.reset_id)
            if _canonical_home_proof(captured.frame, home, DEFAULT_HOME_ATLAS):
                return captured, None
            return None, "commander-talent Home page lacks canonical Atlas proof"
        successor_page = expected_next.get(page.page)
        if successor_page is None:
            return None, f"unexpected commander-talent page after preset verification: {page.page}"
        runtime.back(
            captured,
            action_key=f"training:preset:return-home:{page.page}:{captured.sha256}",
            expected_talent_page=page.page,
        )
        context.checkpoint()
        successor = context.runtime.capture("training-preset-return-home-after")
        recognized = recognize_commander_talent_page(
            successor,
            required_preset="Training",
        )
        if not recognized.recognized or recognized.page != successor_page:
            return None, f"commander-talent Back did not reach exact expected page {successor_page}"
    return None, "commander-talent route exceeded its bounded Home return"


def run_troop_training_native(context, arguments: Mapping[str, object]) -> Mapping[str, object]:
    """Run the fixed four-variant controller through the borrowed native lifecycle."""

    if arguments:
        raise ValueError("troop training does not accept caller-supplied route arguments")
    if (
        context.flow_id,
        context.product_id,
        context.product_revision,
        context.runtime_profile_id,
    ) != (FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
        raise ValueError("troop-training native context does not match the fixed service binding")
    context.checkpoint()
    context.validate_identity()
    identity = context.identity
    initial_home = recognize_home(
        context.initial_frame.frame,
        reset_identity=identity.reset_id,
    )
    if not _canonical_home_proof(
        context.initial_frame.frame,
        initial_home,
        DEFAULT_HOME_ATLAS,
    ):
        raise RuntimeError("troop training requires a fresh canonical Home/Base initial observation")
    context.bind_initial_observation(
        context.initial_frame,
        extra={"troop_training_initial_home_verified": True},
    )
    action_rows = context.action_store.list_actions_for_task(FLOW_ID)
    state = derive_training_action_state(
        action_rows,
        runtime_scope=resource_fixed_runtime_binding().runtime_scope,
        account_id=identity.account_id,
        server_id=identity.server_id,
        game_day_id=identity.reset_id,
    )
    preset_context = {
        "flow_id": FLOW_ID,
        "product_id": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "runtime_profile_id": PROFILE_ID,
        "runtime_scope": resource_fixed_runtime_binding().runtime_scope,
        "account_id": identity.account_id,
        "server_id": identity.server_id,
        "scheduler_reset_id": identity.reset_id,
        "runtime_identity_sha256": state.runtime_identity_sha256,
        "required_preset": "Training",
    }
    route = TroopTrainingIntegratedRoute(
        context.runtime,
        config=default_troop_training_config(),
        reset_identity=identity.reset_id,
        post_input_delay=context.settle_seconds,
        native_context=context,
        runtime_identity_sha256=state.runtime_identity_sha256,
        prior_daily_initiations=tuple(state.prior_daily_initiations),
        queue_generations=state.queue_generations,
        pending_start_action_keys=state.pending_start_action_keys,
        pending_start_reset_ids=state.pending_start_reset_ids,
        next_start_action_keys=state.next_start_action_keys,
        blocked_start_variants=state.blocked_start_variants,
        per_reset_variant_start_counts=state.per_reset_variant_start_counts,
        per_reset_variant_claim_counts=state.per_reset_variant_claim_counts,
        preset_context=preset_context,
    )
    preset_error = route._ensure_training_preset()
    if preset_error is not None:
        result = route._result("blocked", preset_error)
    else:
        _home_capture, home_error = _training_return_to_home_after_preset(
            context,
            route.runtime,
        )
        if home_error is not None:
            result = route._result("blocked", home_error)
        else:
            result = route.run()
    context.checkpoint()
    context.validate_identity()
    accounting = context.accounting()
    completed_at = float(context.utc_clock())
    payload = asdict(result)
    payload.update(
        {
            "flow_id": FLOW_ID,
            "task_id": PRODUCT_ID,
            "native_task_id": FLOW_ID,
            "product_id": PRODUCT_ID,
            "product_revision": PRODUCT_REVISION,
            "runtime_profile_id": PROFILE_ID,
            "account_id": identity.account_id,
            "server_id": identity.server_id,
            "reset_id": identity.reset_id,
            "backend_runtime_scope": resource_fixed_runtime_binding().runtime_scope,
            "runtime_identity_sha256": state.runtime_identity_sha256,
            "total_input_count": accounting.input_count,
            "input_count": accounting.input_count,
            "accounting_verified": accounting.verified,
            "terminal_home_verified": result.terminal_home_verified,
            "training_dispatch_count": result.training_dispatch_count,
            "training_start_transport_calls": result.training_start_transport_calls,
            "claim_dispatch_count": result.claim_dispatch_count,
            "resource_box_dispatch_count": result.resource_box_dispatch_count,
            "warehouse_dispatch_count": result.warehouse_dispatch_count,
            "committed_action_count": result.committed_action_count,
            "effect_reconciliation_required": result.effect_reconciliation_required,
            "identical_retry_denied": result.identical_retry_denied,
            "completed_at_utc": completed_at,
        }
    )
    if (
        result.status == "partial"
        and result.remaining_eligible_variants
        and result.terminal_home_verified
        and accounting.verified
    ):
        payload["next_due_utc"] = completed_at + 60.0
    return payload


def create_service_binding(make_native_route_binding):
    """Bind the fixed route to the canonical service-owned native lifecycle."""

    return make_native_route_binding(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=PROFILE_ID,
        owner="automation-service:troop-training",
        workflow="troop-training-native",
        max_inputs=MAX_INPUTS,
        max_actions=MAX_ACTIONS,
        driver=run_troop_training_native,
    )


