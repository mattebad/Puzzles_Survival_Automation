"""Executable, dry-run-by-default BlueStacks route for Nova Praise.

The adapter consumes current native 800x1280 frames and exposes bound commands to a caller.
It does not register a task or enable the production scheduler.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
import time
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.nova_praise_runtime import NovaPraiseRuntimeController
from tasks.nova_praise import NOVA_PRAISE_TARGET, NOVA_SCREEN
from tasks.nova_praise_vision import (
    NovaFrameRecognition,
    RESEARCH_LAB_UPGRADE_SCREEN,
    ResearchLabTapProvenance,
    recognize_nova_frame,
)
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    IntegratedRouteResult,
    LocalBlueStacksRuntime,
    NativeRuntimePort,
)
from scripts.home_atlas_bluestacks import (
    BlueStacksLocalizeFirstHomeDriver,
    HomeDriverDisposition,
    ScrcpyMotionEventZoomTransport,
)
from scripts.navigation_development_boundary import (
    CANONICAL_ACTION_STORE_PATH,
    NavigationBoundaryError,
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    finalize_navigation_evidence,
    make_source_safety_facts,
    require_fixed_orchestrator_path,
)
from tasks.home_atlas import AmbiguityState, ZoomIdentity, load_home_atlas
from tasks.home_base_vision import recognize_base_surface
from tasks.home_context import (
    HomeContextLevel,
    HomeReadyObservation,
    is_home_canonical,
    localize_home,
)
from tasks.nova_praise import NOVA_INTERACTION_TARGET
from tasks.nova_praise_pulse import RESEARCH_LAB_BUILDING_ID
from tasks.runtime_identity import VerifiedRuntimeIdentity

NovaLabRecognizedHook = Callable[
    [CapturedNativeFrame, NovaFrameRecognition],
    "NovaNavigationCanaryResult | None",
]


def nova_navigation_route_declaration() -> NavigationRouteDeclaration:
    """Nova adapter route declaration for the shared navigation-development boundary."""

    return NavigationRouteDeclaration(
        allowed_source_states=frozenset(
            {
                "HOME_BASE",
                "RESEARCH_LAB_MENU",
                NOVA_SCREEN,
                RESEARCH_LAB_UPGRADE_SCREEN,
            }
        ),
        allowed_target_identities=frozenset(
            {
                RESEARCH_LAB_BUILDING_ID,
                NOVA_INTERACTION_TARGET,
                "home-camera-click-drag",
                "home-zoom-out",
                "system-back",
            }
        ),
        allowed_gesture_classes=frozenset({"tap", "swipe", "back", "zoom_out"}),
    )


@dataclass(frozen=True)
class NovaAdapterConfig:
    dry_run: bool = True
    frame_max_age_seconds: float = 3.0


class BlueStacksNovaPraiseAdapter:
    """Vision-only adapter; transport is an injected callable and disabled by default."""

    def __init__(self, config: NovaAdapterConfig | None = None, *, transport: Callable[[tuple[int, int]], None] | None = None) -> None:
        self.config = config or NovaAdapterConfig()
        self.transport = transport
        self.controller = NovaPraiseRuntimeController()

    def observe(self, frame, *, captured_monotonic: float | None = None, now: float | None = None) -> NovaFrameRecognition:
        stale = bool(
            now is not None
            and captured_monotonic is not None
            and now - captured_monotonic > self.config.frame_max_age_seconds
        )
        return recognize_nova_frame(frame, captured_monotonic=captured_monotonic, stale=stale)

    def command(self, recognition):
        command = self.controller.next_command(recognition)
        if command.action.value == "PRAISE" and not self.config.dry_run:
            raise RuntimeError("Nova Praise dispatch requires the centralized action boundary")
        return command


class NovaNativePartialResultError(RuntimeError):
    """A failed native run with retained, non-success outcome facts.

    The partial result is intentionally unresolved at the route level.  It carries
    only counts and identities retained by the runtime event ledger; callers must
    not promote it to semantic success or retry an identical consequential input.
    """

    def __init__(self, message: str, *, partial_result: dict[str, object]) -> None:
        super().__init__(message)
        if not isinstance(partial_result, dict):
            raise TypeError("Nova partial result must be a mapping")
        self.partial_result = dict(partial_result)


class NovaPraiseIntegratedRoute:
    """Drive Home → Research Lab → Nova → one Praise → verified cooldown → Home."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        controller: NovaPraiseRuntimeController | None = None,
        recognizer=recognize_nova_frame,
        action_boundary=None,
        post_input_delay: float = 1.0,
        postcondition_timeout: float = 20.0,
    ) -> None:
        self.runtime = runtime
        self.controller = controller or NovaPraiseRuntimeController(now=time.monotonic())
        self.recognizer = recognizer
        self.action_boundary = action_boundary
        self.post_input_delay = post_input_delay
        self.postcondition_timeout = postcondition_timeout

    def _observe(self, label: str):
        captured = self.runtime.capture(label)
        recognition = self.recognizer(
            captured.frame,
            captured_monotonic=captured.captured_monotonic,
            stale=False,
        )
        return captured, recognition

    def _return_home(self, captured, recognition, actions: int) -> IntegratedRouteResult:
        if recognition.observation.screen_state == "HOME_BASE":
            return IntegratedRouteResult("completed", "returned_home", actions, str(self.runtime.session))
        if (
            not recognition.observation.recognized
            or recognition.observation.screen_state != NOVA_SCREEN
        ):
            return IntegratedRouteResult(
                "blocked",
                "return_source_not_recognized_nova",
                actions,
                str(self.runtime.session),
            )
        for ordinal in range(1, 2):
            self.runtime.back(captured, action_key=f"nova:return-home:{ordinal}")
            time.sleep(self.post_input_delay)
            captured, recognition = self._observe(f"return-home-post-{ordinal}")
            if (
                recognition.observation.recognized
                and recognition.observation.screen_state == "HOME_BASE"
            ):
                return IntegratedRouteResult(
                    "completed",
                    "returned_home",
                    actions,
                    str(self.runtime.session),
                )
        return IntegratedRouteResult(
            "blocked",
            "home_postcondition_not_recognized",
            actions,
            str(self.runtime.session),
        )

    def run(self, *, max_steps: int = 20) -> IntegratedRouteResult:
        if not self.runtime.execute:
            _, recognition = self._observe("dry-run-source")
            status = "dry-run" if recognition.observation.recognized else "blocked"
            return IntegratedRouteResult(status, f"transport_disabled:{recognition.observation.screen_state}", 0, str(self.runtime.session))
        if self.action_boundary is None:
            return IntegratedRouteResult(
                "blocked",
                "centralized_action_boundary_required",
                0,
                str(self.runtime.session),
            )
        actions = 0
        for step in range(1, max_steps + 1):
            captured, recognition = self._observe(f"step-{step:03d}-source")
            self.controller.now = captured.captured_monotonic
            command = self.controller.next_command(recognition)
            if command.action.value in {"OPEN_LAB", "OPEN_NOVA"}:
                target = recognition.target(command.target_identity or "") or command.target_roi
                self.runtime.tap(
                    captured,
                    target_identity=command.target_identity or "",
                    target_roi=target or (0, 0, 0, 0),
                    action_key=f"nova:{command.action.value.casefold()}:{captured.sha256}",
                )
            elif command.action.value == "PRAISE":
                result = self.action_boundary.execute_praise(captured, recognition)
                if (
                    result.status == "confirmed"
                    and result.after_capture is not None
                    and result.after_recognition is not None
                ):
                    actions += 1
                    return self._return_home(
                        result.after_capture,
                        result.after_recognition,
                        actions,
                    )
                return IntegratedRouteResult(
                    result.status,
                    result.reason,
                    actions,
                    str(self.runtime.session),
                )
            elif command.action.value in {"WAIT_COOLDOWN", "RETURN_HOME"}:
                result = self.action_boundary.record_no_dispatch(
                    recognition.observation,
                    evidence_ref=str(captured.path),
                )
                if result.status not in {"deferred", "complete_for_reset"}:
                    return IntegratedRouteResult(
                        result.status,
                        result.reason,
                        actions,
                        str(self.runtime.session),
                    )
                return self._return_home(captured, recognition, actions)
            else:
                return IntegratedRouteResult("blocked", command.reason or command.action.value, actions, str(self.runtime.session))
            time.sleep(self.post_input_delay)
        return IntegratedRouteResult("blocked", "maximum controller steps exceeded", actions, str(self.runtime.session))


@dataclass(frozen=True)
class NovaNavigationCanaryResult:
    status: str
    reason: str
    navigation_input_count: int
    praise_taps: int
    terminal_home_verified: bool
    records: tuple[dict[str, object], ...]
    session: str
    attempts_before: int | None = None
    attempts_after: int | None = None
    cooldown_seconds: int | None = None
    next_eligible_at: float | None = None
    scheduler_outcome: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "navigation_input_count": self.navigation_input_count,
            "praise_taps": self.praise_taps,
            "terminal_home_verified": self.terminal_home_verified,
            "records": list(self.records),
            "session": self.session,
            "attempts_before": self.attempts_before,
            "attempts_after": self.attempts_after,
            "cooldown_seconds": self.cooldown_seconds,
            "next_eligible_at": self.next_eligible_at,
            "scheduler_outcome": self.scheduler_outcome,
        }


class NovaNavigationCanaryRoute:
    """Bounded no-Praise Home → Research Lab → radial → Nova → Home route."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        identity: VerifiedRuntimeIdentity,
        *,
        atlas_path: Path,
        home_driver: BlueStacksLocalizeFirstHomeDriver | None = None,
        recognizer=recognize_nova_frame,
        zoom_transport=None,
        settle_seconds: float = 1.0,
        maximum_steps: int = 12,
        maximum_return_inputs: int = 3,
        initial_research_lab_tap_provenance: ResearchLabTapProvenance | None = None,
        on_nova_lab_recognized: NovaLabRecognizedHook | None = None,
        route_declaration: NavigationRouteDeclaration | None = None,
    ) -> None:
        declaration = route_declaration or nova_navigation_route_declaration()
        declaration.validate()
        # Shared startup recovery retains this caller's native ledger and owner.
        # Ordinary route navigation still passes through the navigation firewall.
        self._startup_runtime = runtime
        if isinstance(runtime, NavigationGuardedRuntime):
            self.runtime: NativeRuntimePort = runtime
        else:
            self.runtime = NavigationGuardedRuntime(runtime, declaration)
        self.declaration = (
            self.runtime.declaration
            if isinstance(self.runtime, NavigationGuardedRuntime)
            else declaration
        )
        self.identity = identity
        self.atlas_path = atlas_path
        self.atlas = load_home_atlas(atlas_path)
        ready = HomeReadyObservation(True, True, identity, False, False)
        self.home_driver = home_driver or BlueStacksLocalizeFirstHomeDriver(
            self.atlas,
            atlas_path,
            ready,
            RESEARCH_LAB_BUILDING_ID,
        )
        self.recognizer = recognizer
        self.zoom_transport = zoom_transport
        self.settle_seconds = settle_seconds
        self.maximum_steps = maximum_steps
        # The retained transition proves one exact Nova-screen Back only.
        self.maximum_return_inputs = min(max(0, int(maximum_return_inputs)), 1)
        self.initial_research_lab_tap_provenance = initial_research_lab_tap_provenance
        self.on_nova_lab_recognized = on_nova_lab_recognized
        self.records: list[dict[str, object]] = []
        self.input_count = 0
        # Navigation inputs are transport evidence until a positively recognized
        # successor is observed.  Keep reconciliation idempotent at this route
        # boundary so a recovery/return branch cannot emit duplicate terminal rows.
        self._reconciled_action_keys: set[str] = set()
        self._home_localization_cache: dict[str, object] = {}
        self._base_surface_cache: dict[str, object] = {}

    def _capture(self, label: str):
        return self.runtime.capture(label)

    def _prepare_navigation(
        self,
        captured: CapturedNativeFrame,
        *,
        source_state: str,
        recognized: bool,
        overlay_state: str = "none_observed",
        manual_required: bool = False,
        hard_stop: bool = False,
        unknown_state: bool = False,
        target_roi=None,
    ) -> None:
        if not isinstance(self.runtime, NavigationGuardedRuntime):
            raise NavigationBoundaryError("navigation firewall required before transport")
        # Adapter supplies recognition facts only; live package/device/profile/dims bind at dispatch.
        facts = make_source_safety_facts(
            recognized=recognized,
            source_state=source_state,
            overlay_state=overlay_state,
            manual_required=manual_required,
            hard_stop=hard_stop,
            unknown_state=unknown_state,
            frame_sha256=captured.sha256,
            captured_monotonic=captured.captured_monotonic,
            target_roi=target_roi,
        )
        self.runtime.prepare_source_safety(facts)

    def _positive_navigation_permit(
        self,
        captured: CapturedNativeFrame,
        recognition: NovaFrameRecognition,
        *,
        source_state: str | None = None,
    ) -> tuple[str, bool, str, bool, bool, bool]:
        """Return positively measured recognition facts; never promote from allowlist membership."""

        obs = recognition.observation
        surface = source_state or self._navigation_surface(recognition)
        overlay = str(getattr(obs, "overlay_state", "none_observed") or "none_observed")
        overlay_key = overlay.strip().casefold()
        manual_required = overlay_key in {
            "manual",
            "manual_required",
            "account_select",
            "login",
            "captcha",
        }
        hard_stop = overlay_key in {"hard_stop", "hard-stop", "fatal_overlay"}
        if bool(getattr(obs, "stale", False)):
            return surface, False, overlay, manual_required, hard_stop, True

        if surface == NOVA_SCREEN:
            ok = bool(obs.recognized and obs.screen_state == NOVA_SCREEN)
            return NOVA_SCREEN, ok, overlay, manual_required, hard_stop, not ok

        if surface == RESEARCH_LAB_UPGRADE_SCREEN:
            ok = bool(obs.recognized and obs.screen_state == RESEARCH_LAB_UPGRADE_SCREEN)
            return RESEARCH_LAB_UPGRADE_SCREEN, ok, overlay, manual_required, hard_stop, not ok

        if surface == "RESEARCH_LAB_MENU" or self._research_radial_geometry_present(recognition):
            ok = bool(
                (obs.recognized and obs.screen_state == "RESEARCH_LAB_MENU")
                or self._research_radial_geometry_present(recognition)
            )
            return "RESEARCH_LAB_MENU", ok, overlay, manual_required, hard_stop, not ok

        if self._home_localized(captured) or self._home_context_measured(captured):
            return "HOME_BASE", True, overlay, manual_required, hard_stop, False

        return surface, False, overlay, manual_required, hard_stop, True

    def _prepare_from_recognition(
        self,
        captured: CapturedNativeFrame,
        recognition: NovaFrameRecognition,
        *,
        source_state: str | None = None,
        target_roi=None,
    ) -> None:
        surface, recognized, overlay, manual_required, hard_stop, unknown = self._positive_navigation_permit(
            captured,
            recognition,
            source_state=source_state,
        )
        self._prepare_navigation(
            captured,
            source_state=surface,
            recognized=recognized,
            overlay_state=overlay,
            manual_required=manual_required,
            hard_stop=hard_stop,
            unknown_state=unknown,
            target_roi=target_roi,
        )

    def _prepare_home_navigation(
        self,
        captured: CapturedNativeFrame,
        *,
        target_roi=None,
    ) -> None:
        if not self._home_localized(captured):
            raise NavigationBoundaryError("home localization not positively established")
        self._prepare_navigation(
            captured,
            source_state="HOME_BASE",
            recognized=True,
            target_roi=target_roi,
        )

    def _record_input(self, action: str, source, successor, **details) -> None:
        self.records.append(
            {
                "action": action,
                "source_sha256": source.sha256,
                "successor_sha256": successor.sha256,
                **details,
            }
        )
        self.input_count += 1

    def _reconcile_verified_transition(
        self,
        action_key: str,
        successor: CapturedNativeFrame,
        *,
        reason: str,
    ) -> None:
        """Journal one transport only after its semantic successor is verified.

        Navigation success is never inferred from a returned transport call.  The
        caller must invoke this only after its route-specific positive successor
        check.  Dry-run runtimes deliberately remain un-reconciled/unknown.
        """

        if not action_key or not bool(getattr(self.runtime, "execute", False)):
            return
        if action_key in self._reconciled_action_keys:
            return
        self.runtime.reconcile(action_key, "confirmed", successor, reason)
        self._reconciled_action_keys.add(action_key)

    def _recognize(self, captured, *, provenance=None, home_visible=False):
        return self.recognizer(
            captured.frame,
            captured_monotonic=captured.captured_monotonic,
            stale=False,
            research_lab_tap_provenance=provenance,
            home_context_visible=home_visible,
        )

    def _settle(self, immediate_label: str, settled_label: str):
        immediate_post = self._capture(immediate_label)
        if self.settle_seconds > 0:
            time.sleep(self.settle_seconds)
        settled = self._capture(settled_label)
        return immediate_post, settled

    def _home_localization(self, captured):
        localization = self._home_localization_cache.get(captured.sha256)
        if localization is None:
            localization = self.home_driver.localizer.localize(captured.frame)
            self._home_localization_cache[captured.sha256] = localization
        return localization

    def _base_surface_recognition(self, captured):
        recognition = self._base_surface_cache.get(captured.sha256)
        if recognition is None:
            recognition = recognize_base_surface(captured.frame)
            self._base_surface_cache[captured.sha256] = recognition
        return recognition

    def _base_surface_recognized(self, captured) -> bool:
        """Zoom-independent Base/town admission; never consults the bottom nav strip."""

        return bool(self._base_surface_recognition(captured).recognized)

    def _home_localized(self, captured) -> bool:
        localization = self._home_localization(captured)
        decision = localize_home(self.home_driver.ready, localization)
        return decision.level in {
            HomeContextLevel.HOME_LOCALIZED,
            HomeContextLevel.HOME_CANONICAL,
        }

    def _home_canonical(self, captured) -> bool:
        localization = self._home_localization(captured)
        return is_home_canonical(localization)

    def _home_context_measured(self, captured) -> bool:
        localization = self._home_localization(captured)
        decision = localize_home(self.home_driver.ready, localization)
        if decision.level in {
            HomeContextLevel.HOME_LOCALIZED,
            HomeContextLevel.HOME_CANONICAL,
        }:
            return True
        # Noncanonical atlas evidence is only a measured Home context for the
        # existing bounded zoom recovery; it never authorizes a target or transport.
        return bool(
            localization.zoom_identity
            in {ZoomIdentity.ZOOMED_IN, ZoomIdentity.INTERMEDIATE}
            and localization.confidence >= 0.85
            and localization.residual_px is not None
            and localization.residual_px <= 3.0
            and localization.ambiguity_state is AmbiguityState.NONE
            and not localization.stale
            and not localization.overlay
        )

    def _recognize_with_measured_home(self, captured, *, provenance=None):
        # Base-surface OR measured atlas context may establish Home visibility for
        # recognition. Atlas localization remains required for binding/dispatch.
        home_visible = self._base_surface_recognized(captured) or self._home_context_measured(
            captured
        )
        recognition = self._recognize(
            captured,
            provenance=provenance,
            home_visible=home_visible,
        )
        return recognition, home_visible

    _AUTHORIZED_RADIAL_BIND_METHODS = frozenset(
        {
            "template_nova_from_research_tap",
            "template_nova_initial",
        }
    )
    _AMBIGUOUS_RADIAL_BIND_METHODS = frozenset(
        {
            "ambiguous_or_duplicated_template_match",
            "ambiguous_template_pairings",
        }
    )

    @staticmethod
    def _research_radial_corroborated(recognition: NovaFrameRecognition) -> bool:
        """Template-driven radial corroboration; Hough never authorizes surface/geometry."""

        radial = recognition.diagnostics.get("research_lab_radial")
        if not isinstance(radial, dict):
            return False
        obs = recognition.observation
        if obs.recognized and obs.screen_state == "HOME_BASE":
            return False
        if radial.get("recognized"):
            return True
        bind_method = radial.get("bind_method")
        if (
            bind_method in NovaNavigationCanaryRoute._AUTHORIZED_RADIAL_BIND_METHODS
            and recognition.target(NOVA_INTERACTION_TARGET) is not None
        ):
            return True
        # Explicit template ambiguity may fail-closed as radial-like; Hough ambiguity may not.
        if bind_method in NovaNavigationCanaryRoute._AMBIGUOUS_RADIAL_BIND_METHODS:
            return True
        return False

    @staticmethod
    def _navigation_surface(recognition: NovaFrameRecognition) -> str:
        if recognition.observation.recognized and recognition.observation.screen_state == NOVA_SCREEN:
            return NOVA_SCREEN
        if (
            recognition.observation.recognized
            and recognition.observation.screen_state == RESEARCH_LAB_UPGRADE_SCREEN
        ):
            return RESEARCH_LAB_UPGRADE_SCREEN
        if (
            recognition.observation.recognized
            and recognition.observation.screen_state == "HOME_BASE"
        ):
            return "HOME_BASE"
        if (
            recognition.observation.recognized
            and recognition.observation.screen_state == "RESEARCH_LAB_MENU"
        ):
            return "RESEARCH_LAB_MENU"
        if NovaNavigationCanaryRoute._research_radial_corroborated(recognition):
            return "RESEARCH_LAB_MENU"
        return recognition.observation.screen_state

    @staticmethod
    def _research_radial_geometry_present(recognition: NovaFrameRecognition) -> bool:
        if (
            recognition.observation.recognized
            and recognition.observation.screen_state == "HOME_BASE"
        ):
            return False
        if (
            recognition.observation.recognized
            and recognition.observation.screen_state == "RESEARCH_LAB_MENU"
        ):
            return True
        return NovaNavigationCanaryRoute._research_radial_corroborated(recognition)

    def _normalize_known_start_to_home(self, source):
        initial_provenance = self.initial_research_lab_tap_provenance
        current_capture = source
        current_recognition, measured_home = self._recognize_with_measured_home(
            source,
            provenance=initial_provenance,
        )
        for ordinal in range(0, self.maximum_return_inputs + 1):
            surface = self._navigation_surface(current_recognition)
            bound_nova = current_recognition.target(NOVA_INTERACTION_TARGET)
            if self._research_radial_geometry_present(current_recognition):
                if not self._home_localized(current_capture):
                    return None, NovaNavigationCanaryResult(
                        "blocked",
                        "initial_radial_home_context_not_established",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    ), None
                if (
                    current_recognition.observation.recognized
                    and current_recognition.observation.screen_state == "RESEARCH_LAB_MENU"
                    and bound_nova is not None
                ):
                    # Strong initial composite may continue without tap provenance;
                    # route-tapped Research Lab still requires fresh provenance later.
                    return current_capture, None, current_recognition
                radial = current_recognition.diagnostics.get("research_lab_radial")
                if (
                    isinstance(radial, dict)
                    and radial.get("bind_method")
                    in NovaNavigationCanaryRoute._AMBIGUOUS_RADIAL_BIND_METHODS
                ):
                    reason = "initial_radial_ambiguous"
                elif current_recognition.observation.stale:
                    reason = "initial_radial_stale"
                elif initial_provenance is None and not (
                    isinstance(radial, dict)
                    and radial.get("initial_unprovenanced_composite")
                ):
                    reason = "initial_research_lab_radial_not_bound"
                else:
                    reason = "initial_research_lab_radial_not_bound"
                return None, NovaNavigationCanaryResult(
                    "blocked",
                    reason,
                    self.input_count,
                    0,
                    False,
                    tuple(self.records),
                    str(self.runtime.session),
                ), None
            if surface != NOVA_SCREEN and (
                self._base_surface_recognized(current_capture)
                or self._home_context_measured(current_capture)
            ):
                return current_capture, None, None
            if surface != NOVA_SCREEN:
                return None, NovaNavigationCanaryResult(
                    "blocked",
                    "initial_surface_not_home_or_known_nova_context",
                    self.input_count,
                    0,
                    False,
                    tuple(self.records),
                    str(self.runtime.session),
                ), None
            if ordinal >= self.maximum_return_inputs:
                break
            immediate_before = self._capture(
                f"canary-start-return-{ordinal + 1:02d}-immediate-before"
            )
            rebound = self._recognize(immediate_before)
            if self._navigation_surface(rebound) != surface:
                return None, NovaNavigationCanaryResult(
                    "blocked",
                    "initial_safe_return_revalidation_failed",
                    self.input_count,
                    0,
                    False,
                    tuple(self.records),
                    str(self.runtime.session),
                ), None
            self._prepare_from_recognition(immediate_before, rebound)
            action_key = (
                f"nova-canary:start-return:{ordinal + 1}:"
                f"{immediate_before.sha256}"
            )
            self.runtime.back(
                immediate_before,
                action_key=action_key,
            )
            _immediate_post, settled = self._settle(
                f"canary-start-return-{ordinal + 1:02d}-immediate-post",
                f"canary-start-return-{ordinal + 1:02d}-settled",
            )
            self._record_input("known_start_safe_return", immediate_before, settled)
            current_capture = settled
            current_recognition, measured_home = self._recognize_with_measured_home(
                settled,
                provenance=None,
            )
            settled_surface = self._navigation_surface(current_recognition)
            positive_home = settled_surface == "HOME_BASE" and (
                self._home_localized(settled)
                or self._base_surface_recognized(settled)
                or measured_home
            )
            positive_radial = (
                self._research_radial_geometry_present(current_recognition)
                and current_recognition.target(NOVA_INTERACTION_TARGET) is not None
            )
            if positive_home or positive_radial:
                self._reconcile_verified_transition(
                    action_key,
                    settled,
                    reason=(
                        "verified_known_start_home_successor"
                        if positive_home
                        else "verified_known_start_research_lab_successor"
                    ),
                )
        return None, NovaNavigationCanaryResult(
            "blocked",
            "maximum_initial_safe_return_inputs",
            self.input_count,
            0,
            False,
            tuple(self.records),
            str(self.runtime.session),
        ), None

    def _tap_bound_nova(
        self,
        *,
        provenance: ResearchLabTapProvenance | None,
        require_research_lab_tap_provenance: bool = True,
    ) -> NovaNavigationCanaryResult:
        if require_research_lab_tap_provenance and provenance is None:
            return NovaNavigationCanaryResult(
                "blocked",
                "fresh_nova_missing_research_lab_provenance",
                self.input_count,
                0,
                False,
                tuple(self.records),
                str(self.runtime.session),
            )
        nova_before = self._capture("canary-open-nova-immediate-before")
        radial_rebound, _measured_home = self._recognize_with_measured_home(
            nova_before,
            provenance=provenance,
        )
        if not self._home_localized(nova_before):
            return NovaNavigationCanaryResult(
                "blocked",
                "fresh_nova_home_context_not_established",
                self.input_count,
                0,
                False,
                tuple(self.records),
                str(self.runtime.session),
            )
        target = radial_rebound.target(NOVA_INTERACTION_TARGET)
        if (
            not radial_rebound.observation.recognized
            or radial_rebound.observation.screen_state != "RESEARCH_LAB_MENU"
            or target is None
        ):
            return NovaNavigationCanaryResult(
                "blocked",
                "fresh_nova_target_not_bound",
                self.input_count,
                0,
                False,
                tuple(self.records),
                str(self.runtime.session),
            )
        self._prepare_from_recognition(
            nova_before,
            radial_rebound,
            target_roi=target,
        )
        action_key = f"nova-canary:open-nova:{nova_before.sha256}"
        self.runtime.tap(
            nova_before,
            target_identity=NOVA_INTERACTION_TARGET,
            target_roi=target,
            action_key=action_key,
            consequential=False,
        )
        _immediate_post, nova_capture = self._settle(
            "canary-open-nova-immediate-post",
            "canary-open-nova-settled",
        )
        self._record_input("tap_nova_navigation", nova_before, nova_capture)
        nova = self._recognize(nova_capture)
        if (
            not nova.observation.recognized
            or nova.observation.screen_state != NOVA_SCREEN
        ):
            return NovaNavigationCanaryResult(
                "blocked",
                "nova_lab_successor_not_recognized",
                self.input_count,
                0,
                False,
                tuple(self.records),
                str(self.runtime.session),
            )
        self._reconcile_verified_transition(
            action_key,
            nova_capture,
            reason="verified_nova_screen_successor",
        )
        if self.on_nova_lab_recognized is not None:
            seam = self.on_nova_lab_recognized(nova_capture, nova)
            if seam is not None:
                return seam
        return self._return_home(nova_capture, nova)

    def _return_home(self, captured, recognition) -> NovaNavigationCanaryResult:
        current_capture = captured
        current_recognition = recognition
        for ordinal in range(1, self.maximum_return_inputs + 1):
            surface = self._navigation_surface(current_recognition)
            if surface == "HOME_BASE" and self._home_localized(current_capture):
                return NovaNavigationCanaryResult(
                    "completed",
                    "verified_safe_return_home",
                    self.input_count,
                    0,
                    True,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            # Already on Base after a confirmed action: never spend another Back.
            # Attempt bounded zoom recovery when available, else stop unresolved.
            if surface == "HOME_BASE" and self._base_surface_recognized(current_capture):
                recovered = self._recover_canonical_after_return(current_capture, ordinal)
                if recovered is not None:
                    return recovered
                return NovaNavigationCanaryResult(
                    "blocked",
                    "return_base_recognized_awaiting_canonical",
                    self.input_count,
                    0,
                    False,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            if surface != NOVA_SCREEN:
                return NovaNavigationCanaryResult(
                    "blocked",
                    "return_source_not_recognized",
                    self.input_count,
                    0,
                    False,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            immediate_before = self._capture(
                f"canary-return-{ordinal:02d}-immediate-before"
            )
            rebound = self._recognize(immediate_before)
            if self._navigation_surface(rebound) != surface:
                return NovaNavigationCanaryResult(
                    "blocked",
                    "return_source_revalidation_failed",
                    self.input_count,
                    0,
                    False,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            self._prepare_from_recognition(immediate_before, rebound)
            action_key = f"nova-canary:return:{ordinal}:{immediate_before.sha256}"
            self.runtime.back(
                immediate_before,
                action_key=action_key,
            )
            _immediate_post, settled = self._settle(
                f"canary-return-{ordinal:02d}-immediate-post",
                f"canary-return-{ordinal:02d}-settled",
            )
            self._record_input("safe_return_back", immediate_before, settled)
            settled_recognition, _measured_home = self._recognize_with_measured_home(
                settled
            )
            settled_surface = self._navigation_surface(settled_recognition)
            if settled_surface == "HOME_BASE" and self._home_localized(settled):
                self._reconcile_verified_transition(
                    action_key,
                    settled,
                    reason="verified_home_successor",
                )
                return NovaNavigationCanaryResult(
                    "completed",
                    "verified_safe_return_home",
                    self.input_count,
                    0,
                    True,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            if settled_surface == "HOME_BASE" and self._base_surface_recognized(settled):
                self._reconcile_verified_transition(
                    action_key,
                    settled,
                    reason="verified_home_base_successor",
                )
                recovered = self._recover_canonical_after_return(settled, ordinal)
                if recovered is not None:
                    return recovered
                return NovaNavigationCanaryResult(
                    "blocked",
                    "return_base_recognized_awaiting_canonical",
                    self.input_count,
                    0,
                    False,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            current_capture = settled
            current_recognition = settled_recognition
        return NovaNavigationCanaryResult(
            "blocked",
            "maximum_safe_return_inputs",
            self.input_count,
            0,
            False,
            tuple(self.records),
            str(self.runtime.session),
        )

    def _recover_canonical_after_return(self, captured, ordinal: int):
        """After Back lands on Base, recover fully-zoomed-out localization without another Back."""

        if self._home_localized(captured):
            return NovaNavigationCanaryResult(
                "completed",
                "verified_safe_return_home",
                self.input_count,
                0,
                True,
                tuple(self.records),
                str(self.runtime.session),
            )
        if not isinstance(self.runtime, NavigationGuardedRuntime):
            return None
        if self.zoom_transport is None:
            return None
        if not (
            self._home_localized(captured) or self._home_context_measured(captured)
        ):
            return None
        try:
            action_key = f"home-zoom-out:{captured.sha256}"
            self.runtime.dispatch_zoom_out(
                captured,
                make_source_safety_facts(
                    recognized=True,
                    source_state="HOME_BASE",
                    frame_sha256=captured.sha256,
                    captured_monotonic=captured.captured_monotonic,
                ),
                transport=self.zoom_transport.zoom_out_once,
            )
        except Exception:
            return None
        _immediate_post, settled = self._settle(
            f"canary-return-zoom-{ordinal:02d}-immediate-post",
            f"canary-return-zoom-{ordinal:02d}-settled",
        )
        self._record_input("bounded_zoom_out", captured, settled)
        if self._home_localized(settled):
            self._reconcile_verified_transition(
                action_key,
                settled,
                reason="verified_home_after_zoom_successor",
            )
            return NovaNavigationCanaryResult(
                "completed",
                "verified_safe_return_home",
                self.input_count,
                0,
                True,
                tuple(self.records),
                str(self.runtime.session),
            )
        return None

    def run(self) -> NovaNavigationCanaryResult:
        from scripts.startup_recovery import (
            classify_startup_frame, recover_contextual_startup_overlay,
        )

        source = self._capture("canary-source")
        plan = classify_startup_frame("NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE", source.png)
        if plan.status == "recovery_required" and plan.recovery_owner == "shared_home_startup_recovery":
            before = getattr(self._startup_runtime, "input_count", None)
            recovery = None
            try:
                recovery = recover_contextual_startup_overlay(
                    self._startup_runtime, source, source_context="nova-startup",
                    recognize_successor=lambda frame: (
                        self._base_surface_recognized(frame) or self._home_context_measured(frame)
                    ),
                    action_key="nova-initial-startup-overlay",
                    settle_seconds=self.settle_seconds,
                )
            finally:
                after = getattr(self._startup_runtime, "input_count", None)
                consumed = after - before if type(before) is int and type(after) is int else 0
                self.input_count += max(0, consumed)
                self.records.append({
                    "action": "startup_overlay_recovery" if consumed else "no_input_startup_overlay_recovery",
                    "source_sha256": source.sha256,
                    "input_count": max(0, consumed),
                    "reason": recovery.reason if recovery is not None else "startup_recovery_interrupted",
                    "resume_ready": recovery.resume_ready if recovery is not None else False,
                })
            if not recovery.resume_ready or recovery.settled_frame is None:
                return NovaNavigationCanaryResult(
                    "blocked", "startup_overlay:" + recovery.reason, self.input_count, 0,
                    False, tuple(self.records), str(self.runtime.session),
                )
            source = recovery.settled_frame
        _normalized, blocked, bound_radial = self._normalize_known_start_to_home(source)
        if blocked is not None:
            return blocked
        if bound_radial is not None:
            return self._tap_bound_nova(
                provenance=self.initial_research_lab_tap_provenance,
                require_research_lab_tap_provenance=(
                    self.initial_research_lab_tap_provenance is not None
                ),
            )
        provenance: ResearchLabTapProvenance | None = None
        for ordinal in range(1, self.maximum_steps + 1):
            immediate_before = self._capture(
                f"canary-home-{ordinal:02d}-immediate-before"
            )
            step = self.home_driver.observe(immediate_before.frame)
            if step.disposition is HomeDriverDisposition.RECOVER_ZOOM:
                if not isinstance(self.runtime, NavigationGuardedRuntime):
                    return NovaNavigationCanaryResult(
                        "blocked",
                        "navigation_firewall_required_for_host_zoom",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                if self.zoom_transport is None:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        "bounded_zoom_transport_unavailable",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                try:
                    if not (
                        self._home_localized(immediate_before)
                        or self._home_context_measured(immediate_before)
                    ):
                        raise NavigationBoundaryError(
                            "home localization not positively established"
                        )
                    action_key = f"home-zoom-out:{immediate_before.sha256}"
                    self.runtime.dispatch_zoom_out(
                        immediate_before,
                        make_source_safety_facts(
                            recognized=True,
                            source_state="HOME_BASE",
                            frame_sha256=immediate_before.sha256,
                            captured_monotonic=immediate_before.captured_monotonic,
                        ),
                        transport=self.zoom_transport.zoom_out_once,
                    )
                except NavigationBoundaryError as exc:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        str(exc),
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                except Exception as exc:
                    return NovaNavigationCanaryResult(
                        "failed",
                        f"host_zoom_transport_failed:{type(exc).__name__}",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                self.home_driver.record_zoom_input_dispatched(
                    step.source_frame_sha256
                )
                _immediate_post, settled = self._settle(
                    f"canary-zoom-{ordinal:02d}-immediate-post",
                    f"canary-zoom-{ordinal:02d}-settled",
                )
                self._record_input("bounded_zoom_out", immediate_before, settled)
                if self._home_localized(settled) or self._home_context_measured(settled):
                    self._reconcile_verified_transition(
                        action_key,
                        settled,
                        reason="verified_home_after_zoom_successor",
                    )
                continue
            if step.disposition is HomeDriverDisposition.PAN:
                plan = step.plan
                if plan is None or plan.drag_start is None or plan.drag_end is None:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        "home_pan_geometry_missing",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                try:
                    self._prepare_home_navigation(
                        immediate_before,
                        target_roi=(
                            min(plan.drag_start[0], plan.drag_end[0]),
                            min(plan.drag_start[1], plan.drag_end[1]),
                            min(800, max(plan.drag_start[0], plan.drag_end[0]) + 1),
                            min(1280, max(plan.drag_start[1], plan.drag_end[1]) + 1),
                        ),
                    )
                except NavigationBoundaryError as exc:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        str(exc),
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                action_key = f"nova-canary:pan:{ordinal}:{immediate_before.sha256}"
                self.runtime.swipe(
                    immediate_before,
                    start=plan.drag_start,
                    end=plan.drag_end,
                    action_key=action_key,
                    target_identity="home-camera-click-drag",
                )
                _immediate_post, settled = self._settle(
                    f"canary-pan-{ordinal:02d}-immediate-post",
                    f"canary-pan-{ordinal:02d}-settled",
                )
                after_localization = self.home_driver.localizer.localize(settled.frame)
                progress = self.home_driver.record_pan_progress(
                    step.localization,
                    after_localization,
                )
                self._record_input(
                    "bounded_home_pan",
                    immediate_before,
                    settled,
                    progress_reason=progress.reason,
                    progress_accepted=progress.accepted,
                )
                if not progress.accepted:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        f"home_pan_no_progress:{progress.reason}",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                self._reconcile_verified_transition(
                    action_key,
                    settled,
                    reason="verified_accepted_home_pan_successor",
                )
                continue
            if step.disposition is HomeDriverDisposition.BIND:
                self.records.append(
                    {
                        "action": "no_input_rebind_research_lab",
                        "source_sha256": immediate_before.sha256,
                    }
                )
                continue
            if step.disposition is HomeDriverDisposition.COMPLETE and step.binding is not None:
                action_key = (
                    f"nova-canary:open-research-lab:{immediate_before.sha256}"
                )
                try:
                    self._prepare_home_navigation(
                        immediate_before,
                        target_roi=step.binding.target_roi,
                    )
                except NavigationBoundaryError as exc:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        str(exc),
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                self.runtime.tap(
                    immediate_before,
                    target_identity=RESEARCH_LAB_BUILDING_ID,
                    target_roi=step.binding.target_roi,
                    action_key=action_key,
                    consequential=False,
                )
                # Stamp dispatch time after successful transport so long pre-tap
                # preparation cannot age the 30s successor freshness window.
                provenance = ResearchLabTapProvenance(
                    action_key,
                    RESEARCH_LAB_BUILDING_ID,
                    immediate_before.sha256,
                    step.binding.target_roi,
                    time.monotonic(),
                )
                _immediate_post, radial_capture = self._settle(
                    "canary-open-lab-immediate-post",
                    "canary-open-lab-settled",
                )
                self._record_input(
                    "tap_research_lab_navigation",
                    immediate_before,
                    radial_capture,
                )
                radial, measured_home = self._recognize_with_measured_home(
                    radial_capture,
                    provenance=provenance,
                )
                target = radial.target(NOVA_INTERACTION_TARGET)
                if (
                    not measured_home
                    or not radial.observation.recognized
                    or radial.observation.screen_state != "RESEARCH_LAB_MENU"
                    or target is None
                ):
                    return NovaNavigationCanaryResult(
                        "blocked",
                        (
                            "research_lab_radial_home_context_not_established"
                            if not measured_home
                            else "research_lab_radial_not_bound"
                        ),
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                self._reconcile_verified_transition(
                    action_key,
                    radial_capture,
                    reason="verified_research_lab_menu_successor",
                )
                return self._tap_bound_nova(provenance=provenance)
            return NovaNavigationCanaryResult(
                "blocked",
                step.reason,
                self.input_count,
                0,
                False,
                tuple(self.records),
                str(self.runtime.session),
            )
        return NovaNavigationCanaryResult(
            "blocked",
            "maximum_navigation_steps",
            self.input_count,
            0,
            False,
            tuple(self.records),
            str(self.runtime.session),
        )


@dataclass(frozen=True)
class NovaSupervisedOneFreePulseResult:
    status: str
    reason: str
    navigation_input_count: int
    praise_transport_calls: int
    praise_taps: int
    attempts_before: int | None
    attempts_after: int | None
    cooldown_seconds: int | None
    next_eligible_at: float | None
    action_id: str | None
    action_key: str | None
    journal_status: str | None
    scheduler_outcome: str | None
    evidence_refs: tuple[str, ...]
    terminal_home_verified: bool
    records: tuple[dict[str, object], ...]
    session: str
    production_registration: str = "NOT_REGISTERED"
    scheduler_enabled: bool = False

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "navigation_input_count": self.navigation_input_count,
            "praise_transport_calls": self.praise_transport_calls,
            "praise_taps": self.praise_taps,
            "attempts_before": self.attempts_before,
            "attempts_after": self.attempts_after,
            "cooldown_seconds": self.cooldown_seconds,
            "next_eligible_at": self.next_eligible_at,
            "action_id": self.action_id,
            "action_key": self.action_key,
            "journal_status": self.journal_status,
            "scheduler_outcome": self.scheduler_outcome,
            "evidence_refs": list(self.evidence_refs),
            "terminal_home_verified": self.terminal_home_verified,
            "records": list(self.records),
            "session": self.session,
            "production_registration": self.production_registration,
            "scheduler_enabled": self.scheduler_enabled,
        }


class NovaSupervisedOneFreePulseRoute:
    """Compose canary navigation with exactly one centralized Praise, then safe Home return."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        identity: VerifiedRuntimeIdentity,
        *,
        atlas_path: Path,
        action_boundary,
        home_driver: BlueStacksLocalizeFirstHomeDriver | None = None,
        recognizer=recognize_nova_frame,
        zoom_transport=None,
        settle_seconds: float = 1.0,
        maximum_steps: int = 12,
        maximum_return_inputs: int = 3,
        initial_research_lab_tap_provenance: ResearchLabTapProvenance | None = None,
    ) -> None:
        self.action_boundary = action_boundary
        self._praise_invocations = 0
        self._boundary_result = None
        self._no_work_result: NovaNavigationCanaryResult | None = None
        self.canary = NovaNavigationCanaryRoute(
            runtime,
            identity,
            atlas_path=atlas_path,
            home_driver=home_driver,
            recognizer=recognizer,
            zoom_transport=zoom_transport,
            settle_seconds=settle_seconds,
            maximum_steps=maximum_steps,
            maximum_return_inputs=maximum_return_inputs,
            initial_research_lab_tap_provenance=initial_research_lab_tap_provenance,
            on_nova_lab_recognized=self._on_nova_lab_recognized,
        )

    def _fail_closed(
        self,
        status: str,
        reason: str,
        *,
        terminal_home_verified: bool = False,
    ) -> NovaNavigationCanaryResult:
        praise_calls = 0
        if self._boundary_result is not None:
            praise_calls = int(self._boundary_result.transport_calls)
        return NovaNavigationCanaryResult(
            status,
            reason,
            self.canary.input_count,
            praise_calls,
            terminal_home_verified,
            tuple(self.canary.records),
            str(self.canary.runtime.session),
        )

    def _on_nova_lab_recognized(
        self,
        nova_capture: CapturedNativeFrame,
        nova: NovaFrameRecognition,
    ) -> NovaNavigationCanaryResult | None:
        if self._praise_invocations > 0:
            return self._fail_closed("blocked", "duplicate_praise_invocation_prohibited")
        self._praise_invocations += 1
        observation = nova.observation
        if not observation.recognized or observation.screen_state != NOVA_SCREEN:
            return self._fail_closed(
                "blocked",
                "no_work_requires_positive_nova_screen",
            )
        attempts = observation.attempts_remaining
        depleted = type(attempts) is int and attempts == 0
        visible_cooldown = (
            type(attempts) is int
            and attempts > 0
            and observation.cooldown_active is True
            and type(observation.cooldown_seconds) is int
            and observation.cooldown_seconds > 0
            and type(observation.next_eligible_at) in (int, float)
        )
        if depleted or visible_cooldown:
            # A positively recognized depleted/cooldown Nova is benign no-work.
            # It still must return Home before the scheduler may defer it; no
            # Praise transport or fabricated action journal row is created.
            home = self.canary._return_home(nova_capture, nova)
            if home.status != "completed":
                return self._fail_closed(
                    "unresolved",
                    str(home.reason or "nova_no_work_home_return_unresolved"),
                )
            outcome = "complete_for_reset" if depleted else "deferred"
            self._no_work_result = NovaNavigationCanaryResult(
                outcome,
                "verified_nova_no_work_and_safe_return_home",
                home.navigation_input_count,
                0,
                True,
                home.records,
                home.session,
                attempts_before=attempts,
                attempts_after=attempts,
                cooldown_seconds=observation.cooldown_seconds,
                next_eligible_at=observation.next_eligible_at,
                scheduler_outcome=outcome,
            )
            return self._no_work_result
        # No generic popup cleanup around consequential Praise.
        result = self.action_boundary.execute_praise(nova_capture, nova)
        self._boundary_result = result
        if result.status != "confirmed":
            return self._fail_closed(result.status, result.reason)
        if result.after_capture is None or result.after_recognition is None:
            return self._fail_closed("unresolved", "confirmed_praise_missing_after_frame")
        home = self.canary._return_home(result.after_capture, result.after_recognition)
        praise_calls = int(result.transport_calls)
        # Praise already transported; Home failure is unresolved (no identical retry).
        if home.status == "completed":
            status = "completed"
            reason = "confirmed_praise_and_verified_safe_return_home"
            terminal_home = True
        else:
            status = "unresolved"
            reason = str(home.reason or "praise_confirmed_home_return_unresolved")
            terminal_home = False
        return NovaNavigationCanaryResult(
            status,
            reason,
            home.navigation_input_count,
            praise_calls,
            terminal_home,
            home.records,
            home.session,
        )

    def run(self) -> NovaSupervisedOneFreePulseResult:
        navigation = self.canary.run()
        boundary = self._boundary_result
        if boundary is None:
            no_work = self._no_work_result
            return NovaSupervisedOneFreePulseResult(
                status=navigation.status,
                reason=navigation.reason,
                navigation_input_count=navigation.navigation_input_count,
                praise_transport_calls=0,
                praise_taps=0,
                attempts_before=no_work.attempts_before if no_work else None,
                attempts_after=no_work.attempts_after if no_work else None,
                cooldown_seconds=no_work.cooldown_seconds if no_work else None,
                next_eligible_at=no_work.next_eligible_at if no_work else None,
                action_id=None,
                action_key=None,
                journal_status=None,
                scheduler_outcome=no_work.scheduler_outcome if no_work else None,
                evidence_refs=(),
                terminal_home_verified=navigation.terminal_home_verified,
                records=navigation.records,
                session=navigation.session,
            )
        status = navigation.status
        reason = navigation.reason
        terminal_home = navigation.terminal_home_verified
        if boundary.status == "confirmed" and navigation.status == "completed":
            status = "completed"
            reason = "confirmed_praise_and_verified_safe_return_home"
            terminal_home = True
        elif boundary.status == "confirmed":
            # Consequential Praise already occurred; keep unresolved until Home is proven.
            status = "unresolved"
            reason = str(
                navigation.reason or "praise_confirmed_home_return_unresolved"
            )
            terminal_home = False
        elif boundary.status != "confirmed":
            status = boundary.status
            reason = boundary.reason
            terminal_home = False
        return NovaSupervisedOneFreePulseResult(
            status=status,
            reason=reason,
            navigation_input_count=navigation.navigation_input_count,
            praise_transport_calls=int(boundary.transport_calls),
            praise_taps=int(boundary.transport_calls),
            attempts_before=boundary.attempts_before,
            attempts_after=boundary.attempts_after,
            cooldown_seconds=boundary.cooldown_seconds,
            next_eligible_at=boundary.next_eligible_at,
            action_id=boundary.action_id,
            action_key=boundary.action_key,
            journal_status=boundary.journal_status,
            scheduler_outcome=boundary.scheduler_outcome,
            evidence_refs=tuple(boundary.evidence_refs),
            terminal_home_verified=terminal_home,
            records=navigation.records,
            session=navigation.session,
        )


DEFAULT_NOVA_ACTION_DATABASE = CANONICAL_ACTION_STORE_PATH


def run_nova_navigation_canary(args, identity: VerifiedRuntimeIdentity) -> str:
    """Checked-in pnsctl live runner; invoked only by GF-MVP-009 authorization."""

    atlas_path = (
        ROOT
        / "tasks"
        / "assets"
        / "home_atlas"
        / "bluestacks"
        / "800x1280"
        / "atlas.json"
    )
    runtime = LocalBlueStacksRuntime.connect(
        adb=str(args.adb),
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="nova-navigation-canary",
        execute=True,
    )
    route = NovaNavigationCanaryRoute(
        runtime,
        identity,
        atlas_path=atlas_path,
        zoom_transport=ScrcpyMotionEventZoomTransport(
            adb=str(args.adb),
            serial=args.serial,
            evidence_directory=runtime.session / "scrcpy-zoom",
        ),
        settle_seconds=args.settle_seconds,
        route_declaration=nova_navigation_route_declaration(),
    )
    route_error: BaseException | None = None
    result = None
    try:
        result = route.run()
    except BaseException as exc:
        route_error = exc
        finalize_navigation_evidence(
            runtime.session,
            status="failed",
            reason=f"exception:{type(exc).__name__}",
            records=tuple(route.records),
            flow_id="NOVA-PRAISE-HOME-ATLAS-MIGRATION",
            scenario_id="nova_navigation_round_trip_no_praise",
            navigation_input_count=route.input_count,
            authorized_gestures=(
                route.runtime.authorized_gestures
                if isinstance(route.runtime, NavigationGuardedRuntime)
                else ()
            ),
            extra={
                "praise_taps": 0,
                "terminal_home_verified": False,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            exception=exc,
        )
        raise
    assert result is not None
    finalize_navigation_evidence(
        runtime.session,
        status=result.status if result.status in {"completed", "blocked", "manual_required", "unresolved", "failed"} else "blocked",
        reason=result.reason,
        records=result.records,
        flow_id="NOVA-PRAISE-HOME-ATLAS-MIGRATION",
        scenario_id="nova_navigation_round_trip_no_praise",
        navigation_input_count=result.navigation_input_count,
        authorized_gestures=(
            route.runtime.authorized_gestures
            if isinstance(route.runtime, NavigationGuardedRuntime)
            else ()
        ),
        extra={
            "praise_taps": 0,
            "terminal_home_verified": result.terminal_home_verified,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
            "route_declaration": {
                "allowed_source_states": sorted(route.declaration.allowed_source_states),
                "allowed_target_identities": sorted(route.declaration.allowed_target_identities),
                "allowed_gesture_classes": sorted(route.declaration.allowed_gesture_classes),
                "consequence_class": route.declaration.consequence_class,
            },
        },
    )
    return json.dumps(
        {
            "status": result.status,
            "reason": result.reason,
            "scenario_id": "nova_navigation_round_trip_no_praise",
            "session_directory": str(runtime.session),
            "navigation_input_count": result.navigation_input_count,
            "praise_taps": 0,
            "transport_calls": result.navigation_input_count,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        },
        sort_keys=True,
    )


def _nova_native_dispatch_rows(
    runtime: LocalBlueStacksRuntime,
) -> tuple[dict[str, dict[str, object]], bool, str | None]:
    events_path = runtime.events
    dispatches: dict[str, dict[str, object]] = {}
    accounting_error: str | None = None
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return {}, False, f"events ledger unreadable: {type(exc).__name__}"
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            accounting_error = accounting_error or f"events ledger malformed JSON: line {exc.lineno}"
            continue
        if not isinstance(event, dict):
            accounting_error = accounting_error or "events ledger row is not an object"
            continue
        if event.get("type") != "dispatch":
            continue
        if event.get("execute") is not True or event.get("transport_attempted") is False:
            continue
        action_key = event.get("action_key")
        if not isinstance(action_key, str) or not action_key.strip():
            accounting_error = accounting_error or "dispatch row is missing an action_key"
            continue
        previous = dispatches.get(action_key)
        if previous is not None:
            comparable = ("target_identity", "source_sha256", "execute", "transport_attempted")
            if any(previous.get(field) != event.get(field) for field in comparable):
                accounting_error = accounting_error or (
                    f"conflicting duplicate dispatch identity: {action_key}"
                )
            continue
        dispatches[action_key] = event
    return dispatches, accounting_error is None, accounting_error


def _nova_native_partial_result_count(runtime: LocalBlueStacksRuntime) -> int:
    dispatches, _verified, _error = _nova_native_dispatch_rows(runtime)
    return max(len(dispatches), int(getattr(runtime, "input_count", 0)))


def _nova_native_partial_result(
    runtime: LocalBlueStacksRuntime,
    route: object | None,
    *,
    status: str,
    reason: str,
) -> dict[str, object]:
    """Project retained dispatch counts for a failed native invocation."""

    dispatches, accounting_verified, accounting_error = _nova_native_dispatch_rows(runtime)
    events_path = runtime.events
    retained_dispatch_count = len(dispatches)
    runtime_input_count = int(getattr(runtime, "input_count", 0))
    accounting_lower_bound = max(retained_dispatch_count, runtime_input_count)
    praise = sum(
        event.get("target_identity") == NOVA_PRAISE_TARGET
        for event in dispatches.values()
    )
    boundary = getattr(route, "_boundary_result", None)
    boundary_status = getattr(boundary, "status", None)
    return {
        "status": status,
        "reason": reason,
        "session_directory": str(runtime.session),
        "events_path": str(events_path),
        "transport_calls": accounting_lower_bound,
        "total_input_count": accounting_lower_bound,
        "navigation_input_count": max(0, accounting_lower_bound - praise),
        "praise_transport_calls": praise,
        "praise_taps": praise,
        "retained_dispatch_count": retained_dispatch_count,
        "runtime_input_count": runtime_input_count,
        "accounting_lower_bound": accounting_lower_bound,
        "accounting_verified": accounting_verified,
        "accounting_error": accounting_error,
        "max_inputs": int(runtime.max_inputs),
        "action_id": getattr(boundary, "action_id", None),
        "action_key": getattr(boundary, "action_key", None),
        "journal_status": getattr(boundary, "journal_status", None),
        "effect_status": boundary_status or "unknown",
        "effect_reconciliation_required": not (
            praise > 0 and boundary_status == "confirmed"
        ),
        "semantic_status": "unknown",
        "terminal_home_verified": False,
        "terminal_home_status": "unknown",
        "identical_retry_denied": True,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }


def run_nova_praise_one_free_pulse(args, identity: VerifiedRuntimeIdentity) -> str:
    """Checked-in supervised one-Praise runner; uses durable SafetyStore and canary composition."""

    checkpoint = getattr(args, "checkpoint", None)
    if checkpoint is not None and not callable(checkpoint):
        raise RuntimeError("Nova runtime checkpoint must be callable")
    raw_max_inputs = getattr(args, "max_inputs", 8)
    if type(raw_max_inputs) is not int or not 1 <= raw_max_inputs <= 8:
        raise RuntimeError("Nova max_inputs must be an integer between 1 and 8")
    max_inputs = raw_max_inputs

    from safe_action_core import SafetyStore
    from scripts.nova_praise_centralized import NovaPraiseActionBoundary
    from tasks.nova_praise_pulse import NOVA_TASK_ID, NovaPulseController
    from tasks.scheduler_task_result import SchedulerIdentity

    atlas_path = (
        ROOT
        / "tasks"
        / "assets"
        / "home_atlas"
        / "bluestacks"
        / "800x1280"
        / "atlas.json"
    )
    database = Path(
        getattr(args, "action_database", None) or DEFAULT_NOVA_ACTION_DATABASE
    )
    database = require_fixed_orchestrator_path(
        database,
        CANONICAL_ACTION_STORE_PATH,
        "canonical action store",
    )
    database.parent.mkdir(parents=True, exist_ok=True)
    utc_clock = getattr(args, "utc_clock", time.time)
    monotonic_clock = getattr(args, "monotonic_clock", time.monotonic)
    if not callable(utc_clock) or not callable(monotonic_clock):
        raise RuntimeError("Nova paired clocks must be callable")
    owner = str(getattr(args, "owner", None) or "nova-praise-supervised")
    invocation_id = str(
        getattr(args, "invocation_id", None)
        or f"nova-praise-one-free-{int(utc_clock())}"
    )
    lease_ttl = float(getattr(args, "lease_ttl", 3600.0) or 3600.0)
    runtime = LocalBlueStacksRuntime.connect(
        adb=str(args.adb),
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="nova-praise-one-free-pulse",
        execute=True,
    )
    runtime.checkpoint = checkpoint
    runtime.max_inputs = max_inputs
    store = SafetyStore(database)
    leased = False
    result = None
    route = None
    route_error: BaseException | None = None
    lease_release_error: BaseException | None = None
    try:
        if store.has_action_block():
            raise RuntimeError(
                "canonical unresolved or nonterminal action blocks supervised Praise"
            )
        store.acquire_lease(owner, utc_clock(), lease_ttl)
        leased = True
        pulse = NovaPulseController(
            SchedulerIdentity(
                identity.account_id,
                identity.server_id,
                identity.reset_id,
                NOVA_TASK_ID,
            ),
            load_home_atlas(atlas_path),
            now=monotonic_clock(),
            replay_mode=False,
        )
        boundary = NovaPraiseActionBoundary(
            runtime,
            store,
            pulse,
            runtime_scope=identity.runtime_scope,
            owner_id=owner,
            invocation_id=invocation_id,
            execute=True,
            monotonic_clock=monotonic_clock,
            wall_clock=utc_clock,
        )
        route = NovaSupervisedOneFreePulseRoute(
            runtime,
            identity,
            atlas_path=atlas_path,
            action_boundary=boundary,
            zoom_transport=ScrcpyMotionEventZoomTransport(
                adb=str(args.adb),
                serial=args.serial,
                evidence_directory=runtime.session / "scrcpy-zoom",
            ),
            settle_seconds=args.settle_seconds,
        )
        result = route.run()
    except BaseException as exc:
        route_error = exc
        finalize_navigation_evidence(
            runtime.session,
            status="failed",
            reason=f"exception:{type(exc).__name__}",
            records=tuple(route.canary.records) if route is not None else (),
            flow_id="NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
            scenario_id="nova_praise_one_free_pulse",
            navigation_input_count=route.canary.input_count if route is not None else 0,
            authorized_gestures=(
                route.canary.runtime.authorized_gestures
                if route is not None and isinstance(route.canary.runtime, NavigationGuardedRuntime)
                else ()
            ),
            extra={
                "action_database": str(database),
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            exception=exc,
        )
    finally:
        if leased:
            try:
                store.release_lease(owner, utc_clock())
            except BaseException as exc:
                lease_release_error = exc
        store.close()

    if result is not None:
        finalize_navigation_evidence(
            runtime.session,
            status=result.status
            if result.status
            in {
                "completed",
                "deferred",
                "complete_for_reset",
                "blocked",
                "manual_required",
                "unresolved",
                "failed",
            }
            else "blocked",
            reason=result.reason,
            records=result.records,
            flow_id="NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE",
            scenario_id="nova_praise_one_free_pulse",
            navigation_input_count=result.navigation_input_count,
            authorized_gestures=(
                route.canary.runtime.authorized_gestures
                if route is not None and isinstance(route.canary.runtime, NavigationGuardedRuntime)
                else ()
            ),
            extra={
                **result.to_mapping(),
                "session_directory": str(runtime.session),
                "action_database": str(database),
                "events_path": "events.jsonl",
                "ledger_path": "ledger.jsonl",
                "journal_path": "journal.jsonl",
            },
        )
        # Preserve Praise-specific journal row for supervised verification.
        with (runtime.session / "journal.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    {
                        "scenario_id": "nova_praise_one_free_pulse",
                        "status": result.status,
                        "navigation_input_count": result.navigation_input_count,
                        "praise_transport_calls": result.praise_transport_calls,
                        "action_id": result.action_id,
                        "action_key": result.action_key,
                        "journal_status": result.journal_status,
                        "scheduler_outcome": result.scheduler_outcome,
                        "attempts_before": result.attempts_before,
                        "attempts_after": result.attempts_after,
                        "cooldown_seconds": result.cooldown_seconds,
                        "next_eligible_at": result.next_eligible_at,
                        "terminal_home_verified": result.terminal_home_verified,
                        "evidence_refs": list(result.evidence_refs),
                    },
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )

    if route_error is not None:
        # Preserve process-control interrupts exactly; ordinary failures carry
        # retained counts so the service can account for attempted inputs before
        # blocking the run.  Neither path claims a semantic success.
        if isinstance(route_error, (KeyboardInterrupt, SystemExit)):
            raise route_error
        detail = f"native route failed: {type(route_error).__name__}: {route_error}"
        if lease_release_error is not None:
            detail = (
                f"{detail}; lease release also failed without overwriting journal "
                f"(status={getattr(result, 'status', None)}): {lease_release_error}"
            )
        partial = _nova_native_partial_result(
            runtime,
            route,
            status="unresolved" if _nova_native_partial_result_count(runtime) > 0 else "blocked",
            reason=detail,
        )
        raise NovaNativePartialResultError(detail, partial_result=partial) from route_error
    if result is None:
        raise RuntimeError("supervised pulse produced no result")
    if lease_release_error is not None:
        detail = (
            f"SafetyStore lease release failed after status={result.status}; "
            f"action journal was not overwritten: {lease_release_error}"
        )
        partial = _nova_native_partial_result(
            runtime,
            route,
            status="unresolved" if _nova_native_partial_result_count(runtime) > 0 else "blocked",
            reason=detail,
        )
        raise NovaNativePartialResultError(detail, partial_result=partial) from lease_release_error

    completed_at_utc = float(utc_clock())
    monotonic_now = float(monotonic_clock())
    next_eligible_at_utc = None
    if result.next_eligible_at is not None:
        if type(result.next_eligible_at) not in (int, float):
            raise RuntimeError("Nova monotonic cooldown deadline is invalid")
        next_eligible_at_utc = completed_at_utc + (
            float(result.next_eligible_at) - monotonic_now
        )
    return json.dumps(
        {
            "status": result.status,
            "reason": result.reason,
            "scenario_id": "nova_praise_one_free_pulse",
            "session_directory": str(runtime.session),
            "navigation_input_count": result.navigation_input_count,
            "praise_transport_calls": result.praise_transport_calls,
            "praise_taps": result.praise_taps,
            "transport_calls": result.navigation_input_count + result.praise_transport_calls,
            "attempts_before": result.attempts_before,
            "attempts_after": result.attempts_after,
            "cooldown_seconds": result.cooldown_seconds,
            "next_eligible_at": next_eligible_at_utc,
            "next_eligible_at_utc": next_eligible_at_utc,
            "action_id": result.action_id,
            "action_key": result.action_key,
            "journal_status": result.journal_status,
            "scheduler_outcome": result.scheduler_outcome,
            "evidence_refs": list(result.evidence_refs),
            "terminal_home_verified": result.terminal_home_verified,
            "action_database": str(database),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
            "time_basis": "utc",
            "completed_at_utc": completed_at_utc,
        },
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm the exact local BlueStacks target non-interactively")
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/nova-praise-integrated"))
    args = parser.parse_args(argv)
    if args.execute:
        parser.error(
            "direct live execution is blocked; use "
            "`pnsctl nova-praise-pulse --live --yes --supervised-live-opt-in` "
            "as the sole supported operational interface"
        )
    if args.execute and not args.yes:
        parser.error("--execute requires --yes")
    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="nova-praise",
        execute=False,
    )
    route = NovaPraiseIntegratedRoute(runtime)
    result = route.run()
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0 if result.status in {"completed", "dry-run"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
