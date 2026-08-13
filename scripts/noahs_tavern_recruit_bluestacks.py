"""Executable, dry-run-by-default native BlueStacks route for Noah's Tavern recruits.

The adapter is deliberately unregistered and has no Claim or scheduler path.  A caller supplies
the frame capture and transport functions; transport is enabled only by an explicit config.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
from pathlib import Path
import sys
import time
from typing import Callable

import cv2
import pytesseract

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.noahs_tavern_recruit_runtime import NoahAction, NoahTavernRecruitRuntimeController
from tasks.noahs_tavern_recruit_maintenance import (
    MAINTENANCE_TASK_ID,
    NoahMaintenancePassResult,
    NoahMaintenanceState,
    TierPassEvidence,
)
from tasks.scheduler_task_result import SchedulerIdentity
from tasks.noahs_tavern_recruit import (
    HERO_RECRUIT_RESULT_SCREEN,
    HOME_BASE_SCREEN,
    NOAHS_TAVERN_SCREEN,
    NOAHS_TAVERN_TIER_TARGET_PREFIX,
    RecruitTier,
)
from tasks.noahs_tavern_recruit_vision import recognize_noahs_tavern_frame
from tasks.home_atlas import ZoomIdentity, load_home_atlas
from tasks.home_atlas_vision import BlueStacksHomeLocalizer, bind_visible_building, frame_digest
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    IntegratedRouteResult,
    LocalBlueStacksRuntime,
    NativeRuntimePort,
)
from scripts.navigation_development_boundary import (
    NavigationBoundaryError,
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    finalize_navigation_evidence,
    make_source_safety_facts,
)


NOAHS_TAVERN_BUILDING_TARGET = "noahs-tavern-building"
NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID = "home.building.noahs_tavern"
NOAHS_TAVERN_SAFE_EXIT_TARGET = "noahs-tavern-safe-exit"
NOAHS_TAVERN_NAV_FLOW_ID = "NOAHS-TAVERN-HOME-ATLAS-MIGRATION"
NOAHS_TAVERN_NAV_SCENARIO_ID = "noahs_tavern_navigation_round_trip_no_recruit"
NOAHS_TAVERN_HOME_ATLAS_PATH = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"


def _write_unified_result(runtime: LocalBlueStacksRuntime, payload: dict[str, object]) -> str:
    """Persist a terminal unified-session result, including blocked/exception paths."""

    path = runtime.session / "unified-recruitment-result.json"
    path.write_text(json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    return json.dumps(payload, sort_keys=True, default=str)


def recognize_home_zoom_source(frame, *, home_classifier=None) -> tuple[bool, dict[str, object]]:
    """Recognize Home for bounded camera normalization without requiring Tavern OCR.

    Home-ready proof uses the existing independent stable-region/HQ/HUD classifier. Tavern
    OCR/box association remains a later Atlas-binding requirement and is intentionally not a
    prerequisite for a zoom gesture while the camera is too close to show the Tavern label.
    """

    if home_classifier is None:
        from scripts.startup_normalization import classify_home_base_live

        home_classifier = lambda image: classify_home_base_live(
            image, cash_mall_rejected=True, safe_os_surface=True
        )
    facts = dict(home_classifier(frame))
    overlay = bool(
        facts.get("overlay")
        or facts.get("blocking_unknown_modal")
        or facts.get("manual_only_state")
    )
    recognized = bool(
        facts.get("state") == HOME_BASE_SCREEN
        and facts.get("recognized")
        and not overlay
    )
    facts["overlay_rejected"] = overlay
    return recognized, facts


def record_home_zoom_recovery_input(home_driver, step) -> None:
    """Record a dispatched zoom against the Home driver's semantic planned-frame identity."""

    home_driver.record_zoom_input_dispatched(step.source_frame_sha256)


def _atlas_canonical_home(localization, observation) -> bool:
    """Accept strong canonical Atlas proof absent a positive conflicting screen."""

    return bool(
        localization.recognized
        and localization.zoom_identity is ZoomIdentity.FULLY_ZOOMED_OUT
        and not localization.overlay
        and not (
            observation.recognized
            and observation.screen_state != HOME_BASE_SCREEN
        )
    )


def _noahs_tavern_binding_ocr(image, psm: int) -> str:
    """Keep the Atlas label association tolerant to the native renderer's clipped final n."""

    raw = pytesseract.image_to_string(image, config=f"--psm {psm}")
    folded = " ".join(raw.casefold().replace("'", " ").split())
    if "noah" in folded and "taver" in folded:
        return f"{raw}\nNoah's Tavern"
    return raw


def noahs_tavern_navigation_route_declaration() -> NavigationRouteDeclaration:
    """Noah's Tavern adapter route declaration for the shared navigation-development boundary.

    Navigation-only: it deliberately omits the ordinary ``noahs-tavern-daily-free`` target so
    the shared firewall cannot dispatch a recruit through this route.
    """

    tier_targets = frozenset(
        NOAHS_TAVERN_TIER_TARGET_PREFIX + tier.name for tier in RecruitTier
    )
    return NavigationRouteDeclaration(
        allowed_source_states=frozenset({HOME_BASE_SCREEN, NOAHS_TAVERN_SCREEN}),
        allowed_target_identities=frozenset({NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID, NOAHS_TAVERN_SAFE_EXIT_TARGET})
        | tier_targets,
        allowed_gesture_classes=frozenset({"tap", "back"}),
    )


@dataclass(frozen=True)
class NoahAdapterConfig:
    dry_run: bool = True
    frame_max_age_seconds: float = 3.0


class BlueStacksNoahsTavernRecruitAdapter:
    """Native vision boundary with injected transport and dormant production registration."""

    def __init__(
        self,
        config: NoahAdapterConfig | None = None,
        *,
        transport: Callable[[tuple[int, int]], None] | None = None,
    ) -> None:
        self.config = config or NoahAdapterConfig()
        self.transport = transport
        self.controller = NoahTavernRecruitRuntimeController()

    def observe(self, frame, *, captured_monotonic: float | None = None, now: float | None = None):
        stale = bool(
            now is not None
            and captured_monotonic is not None
            and now - captured_monotonic > self.config.frame_max_age_seconds
        )
        return recognize_noahs_tavern_frame(frame, captured_monotonic=captured_monotonic, stale=stale)

    def command(self, recognition):
        command = self.controller.next_command(recognition)
        if command.action == NoahAction.RECRUIT_FREE and not self.config.dry_run:
            if self.transport is None:
                raise RuntimeError("Noah's Tavern transport is not configured")
            if command.target_roi is None:
                raise RuntimeError("Noah's Tavern command has no current-frame target")
            x0, y0, x1, y1 = command.target_roi
            self.transport(((x0 + x1) // 2, (y0 + y1) // 2))
        return command


class NoahTavernIntegratedRoute:
    """Drive navigation, one or more free recruits, result closure, and Home return."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        max_recruits: int = 3,
        controller: NoahTavernRecruitRuntimeController | None = None,
        recognizer=recognize_noahs_tavern_frame,
        post_input_delay: float = 1.0,
        result_timeout: float = 20.0,
        atlas_binding: Callable[[CapturedNativeFrame], tuple[int, int, int, int] | None] | None = None,
    ) -> None:
        if max_recruits < 1 or max_recruits > 3:
            raise ValueError("Noah route max_recruits must be between 1 and 3")
        self.runtime = runtime
        self.max_recruits = max_recruits
        self.controller = controller or NoahTavernRecruitRuntimeController(now=time.monotonic())
        self.recognizer = recognizer
        self.post_input_delay = post_input_delay
        self.result_timeout = result_timeout
        # Home entry is always authorized by a current-frame canonical Atlas binder.  Tests and
        # sealed replays inject an independent binder; production defaults to the shared Atlas
        # strategy and never falls back to the recognition ROI.
        self.atlas_binding = atlas_binding or self._default_atlas_binding
        self.pending_result = None
        self.pending_action_key: str | None = None

    def run_maintenance_pass(
        self,
        evidence: dict[RecruitTier, TierPassEvidence],
        terminal_home,
        *,
        identity: SchedulerIdentity | None = None,
        now: float | None = None,
    ) -> NoahMaintenancePassResult:
        """Use the same shared maintenance engine as the production controller seam."""

        return self.controller.run_maintenance_pass(evidence, terminal_home, identity=identity, now=now)

    @staticmethod
    def _wrap(observation):
        return type("NoahRecognition", (), {"observation": observation, "frame_sha256": observation.frame_sha256})()

    def _observe(self, label: str):
        captured = self.runtime.capture(label)
        observation = self.recognizer(captured.frame, captured_monotonic=captured.captured_monotonic)
        return captured, self._wrap(observation)

    def _wait_for_result(self):
        deadline = time.monotonic() + self.result_timeout
        while time.monotonic() < deadline:
            captured, recognition = self._observe("recruit-immediate-post")
            if recognition.observation.screen_state == "HERO_RECRUIT_RESULT" and recognition.observation.recognized:
                return captured, recognition
            time.sleep(min(0.5, self.post_input_delay))
        return None, None

    def _navigation_route(self) -> NoahTavernNavigationCanaryRoute:
        """Compose the canonical Atlas/safe-exit route semantics for recruitment navigation."""

        return NoahTavernNavigationCanaryRoute(
            self.runtime,
            recognizer=self.recognizer,
            settle_seconds=self.post_input_delay,
            maximum_return_inputs=1,
        )

    def _default_atlas_binding(self, captured: CapturedNativeFrame):
        """Canonical production Atlas binding for the current native frame."""

        return self._navigation_route()._atlas_binding(captured)

    def _return_home(self, captured, recognition, actions: int) -> IntegratedRouteResult:
        navigation = self._navigation_route()
        result = navigation._return_home(captured, recognition.observation)
        return IntegratedRouteResult(result.status, result.reason, actions, result.session)

    def resume_unresolved_result(
        self,
        *,
        before_frame: Path,
        result_frame: Path,
        action_key: str,
        tier: RecruitTier,
    ) -> IntegratedRouteResult:
        """Continue one retained unresolved recruit from its explicit result; never recruit again."""

        if not self.runtime.execute:
            return IntegratedRouteResult("dry-run", "resume_transport_disabled", 0, str(self.runtime.session))
        frame = read_frame(before_frame)
        before = self.recognizer(frame, captured_monotonic=time.monotonic())
        if before.screen_state != NOAHS_TAVERN_SCREEN or before.selected_tier != tier or not before.recognized:
            return IntegratedRouteResult("blocked", "retained_recruit_source_not_recognized", 0, str(self.runtime.session))
        self.controller.progress.awaiting_postcondition = True
        self.controller.progress.awaiting_tier = tier
        self.controller.progress.awaiting_before = before
        self.controller._remember_tier(before, tier)
        self.controller.progress.dispatched_action_keys.add(action_key)
        self.controller.progress.last_dispatch_state = "resumed_unresolved_result"
        self.runtime.in_flight_action = action_key

        captured, recognition = self._observe("resume-current-source")
        if recognition.observation.screen_state == NOAHS_TAVERN_SCREEN:
            retained_result = self.recognizer(read_frame(result_frame), captured_monotonic=captured.captured_monotonic)
            if retained_result.screen_state != HERO_RECRUIT_RESULT_SCREEN or not retained_result.recognized:
                return IntegratedRouteResult("unresolved", "retained_result_screen_not_recognized", 0, str(self.runtime.session))
            result_recognition = self._wrap(replace(retained_result, result_tier=tier))
            if not self.controller.accept_postcondition(result_recognition, recognition.observation):
                self.runtime.reconcile(action_key, "unresolved", captured, "retained result/cooldown not proven")
                return IntegratedRouteResult("unresolved", "retained_postcondition_not_proven", 0, str(self.runtime.session))
            self.runtime.reconcile(action_key, "confirmed", captured, "retained explicit result and active cooldown verified")
            return self._return_home(captured, recognition, 1)
        if recognition.observation.screen_state != HERO_RECRUIT_RESULT_SCREEN or not recognition.observation.recognized:
            return IntegratedRouteResult("unresolved", "current_result_screen_not_recognized", 0, str(self.runtime.session))
        result_observation = replace(recognition.observation, result_tier=tier)
        result_recognition = self._wrap(result_observation)
        command = self.controller.next_command(result_recognition, now=captured.captured_monotonic)
        if command.action != NoahAction.CLOSE_RESULT or command.target_roi is None:
            return IntegratedRouteResult("unresolved", command.reason or "safe_result_close_not_authorized", 0, str(self.runtime.session))
        self.runtime.tap(
            captured,
            target_identity=command.target_identity or "noahs-tavern-result-close",
            target_roi=command.target_roi,
            action_key=f"{action_key}:recovery-close",
            continuation_of=action_key,
        )
        time.sleep(self.post_input_delay)
        after_capture, after_recognition = self._observe("resume-after-close")
        if not self.controller.accept_postcondition(result_recognition, after_recognition.observation):
            self.runtime.reconcile(action_key, "unresolved", after_capture, "recovery decrement/cooldown not proven")
            return IntegratedRouteResult("unresolved", "recovery_postcondition_not_proven", 0, str(self.runtime.session))
        self.runtime.reconcile(action_key, "confirmed", after_capture, "retained result, decrement, and cooldown verified")
        return self._return_home(after_capture, after_recognition, 1)

    def run(self, *, max_steps: int = 40) -> IntegratedRouteResult:
        if not self.runtime.execute:
            _, recognition = self._observe("dry-run-source")
            status = "dry-run" if recognition.observation.recognized else "blocked"
            return IntegratedRouteResult(status, f"transport_disabled:{recognition.observation.screen_state}", 0, str(self.runtime.session))
        actions = 0
        for step in range(1, max_steps + 1):
            captured, recognition = self._observe(f"step-{step:03d}-source")
            if step == 1 and not recognition.observation.recognized:
                target_roi = self.atlas_binding(captured)
                if target_roi is not None:
                    self.runtime.tap(
                        captured,
                        target_identity=NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID,
                        target_roi=target_roi,
                        action_key=f"noah:open:{captured.sha256}",
                    )
                    time.sleep(self.post_input_delay)
                    continue
            command = self.controller.next_command(recognition, now=captured.captured_monotonic)
            if actions >= self.max_recruits and command.action not in {NoahAction.CLOSE_RESULT}:
                return self._return_home(captured, recognition, actions)
            if command.action == NoahAction.OPEN_TAVERN:
                target_roi = self.atlas_binding(captured)
                if target_roi is None:
                    return IntegratedRouteResult("blocked", "home_atlas_tavern_binding_not_proven", actions, str(self.runtime.session))
                self.runtime.tap(captured, target_identity=NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID, target_roi=target_roi, action_key=f"noah:open:{captured.sha256}")
            elif command.action == NoahAction.SELECT_TIER:
                self.runtime.tap(captured, target_identity=command.target_identity or "", target_roi=command.target_roi or (0, 0, 0, 0), action_key=f"noah:tier:{command.tier.name}:{captured.sha256}")
            elif command.action == NoahAction.RECRUIT_FREE:
                action_key = command.action_key or f"noah:recruit:{captured.sha256}"
                self.runtime.tap(
                    captured,
                    target_identity=command.target_identity or "",
                    target_roi=command.target_roi or (0, 0, 0, 0),
                    action_key=action_key,
                )
                self.pending_action_key = action_key
                time.sleep(self.post_input_delay)
                post, result = self._wait_for_result()
                if post is None or result is None:
                    return IntegratedRouteResult("unresolved", "recruit_result_not_recognized", actions, str(self.runtime.session))
                self.pending_result = result
                continue
            elif command.action == NoahAction.CLOSE_RESULT:
                if self.pending_result is None or self.pending_action_key is None:
                    return IntegratedRouteResult("blocked", "missing_pending_result", actions, str(self.runtime.session))
                self.runtime.tap(
                    captured,
                    target_identity=command.target_identity or "",
                    target_roi=command.target_roi or (0, 0, 0, 0),
                    action_key=f"{self.pending_action_key}:close",
                )
                time.sleep(self.post_input_delay)
                after_capture, after_recognition = self._observe("recruit-after-close")
                if not self.controller.accept_postcondition(self.pending_result, after_recognition.observation):
                    return IntegratedRouteResult("unresolved", "recruit_postcondition_not_proven", actions, str(self.runtime.session))
                actions += 1
                self.pending_result = None
                self.pending_action_key = None
                if actions >= self.max_recruits:
                    return self._return_home(after_capture, after_recognition, actions)
                continue
            elif command.action == NoahAction.WAIT_COOLDOWN:
                return self._return_home(captured, recognition, actions)
            elif command.action == NoahAction.RETURN_HOME:
                return self._return_home(captured, recognition, actions)
            else:
                return IntegratedRouteResult("blocked", command.reason or command.action.value, actions, str(self.runtime.session))
            time.sleep(self.post_input_delay)
        return IntegratedRouteResult("blocked", "maximum controller steps exceeded", actions, str(self.runtime.session))


@dataclass(frozen=True)
class NoahTavernNavigationResult:
    status: str
    reason: str
    navigation_input_count: int
    recruit_taps: int
    terminal_home_verified: bool
    records: tuple[dict[str, object], ...]
    session: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "navigation_input_count": self.navigation_input_count,
            "recruit_taps": self.recruit_taps,
            "terminal_home_verified": self.terminal_home_verified,
            "records": list(self.records),
            "session": self.session,
        }


class NoahTavernNavigationCanaryRoute:
    """Bounded no-recruit Home -> Noah's Tavern -> Home route over the shared boundary.

    This is the Phase 3 reusability proof for the flow-agnostic navigation-development boundary.
    It reuses only task-specific recognition/route logic; the shared lock, transport firewall,
    current-frame verifier, and evidence finalizer come from the boundary. The recruit endpoint is
    intentionally excluded: it is neither declared nor dispatched here, and this route remains
    navigation-only.
    """

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        recognizer=recognize_noahs_tavern_frame,
        route_declaration: NavigationRouteDeclaration | None = None,
        settle_seconds: float = 1.0,
        maximum_steps: int = 8,
        maximum_return_inputs: int = 1,
        atlas_path: Path | None = None,
        home_localizer=None,
    ) -> None:
        declaration = route_declaration or noahs_tavern_navigation_route_declaration()
        declaration.validate()
        if isinstance(runtime, NavigationGuardedRuntime):
            self.runtime: NativeRuntimePort = runtime
        else:
            self.runtime = NavigationGuardedRuntime(runtime, declaration)
        self.declaration = (
            self.runtime.declaration
            if isinstance(self.runtime, NavigationGuardedRuntime)
            else declaration
        )
        self.recognizer = recognizer
        self.settle_seconds = settle_seconds
        self.maximum_steps = maximum_steps
        # A Tavern safe exit is one positively recognized navigation input.  Keep the
        # argument for source compatibility, but never permit a repeated Back loop.
        self.maximum_return_inputs = min(1, max(0, int(maximum_return_inputs)))
        self.atlas_path = atlas_path or NOAHS_TAVERN_HOME_ATLAS_PATH
        self.atlas = load_home_atlas(self.atlas_path)
        self._home_localizer_injected = home_localizer is not None
        self.home_localizer = home_localizer or BlueStacksHomeLocalizer(
            self.atlas, self.atlas_path
        )
        self.records: list[dict[str, object]] = []
        self.input_count = 0

    def _capture(self, label: str) -> CapturedNativeFrame:
        return self.runtime.capture(label)

    def _recognize(self, captured: CapturedNativeFrame):
        # recognize_noahs_tavern_frame returns a bare NoahTavernObservation.
        return self.recognizer(captured.frame, captured_monotonic=captured.captured_monotonic)

    def _observe(self, label: str):
        captured = self._capture(label)
        return captured, self._recognize(captured)

    def _settle(self, immediate_label: str, settled_label: str):
        immediate_post = self._capture(immediate_label)
        if self.settle_seconds > 0:
            time.sleep(self.settle_seconds)
        settled = self._capture(settled_label)
        return immediate_post, settled

    def _record_input(self, action: str, source: CapturedNativeFrame, successor: CapturedNativeFrame, **details) -> None:
        self.records.append(
            {
                "action": action,
                "source_sha256": source.sha256,
                "successor_sha256": successor.sha256,
                **details,
            }
        )
        self.input_count += 1

    def _prepare(self, captured: CapturedNativeFrame, *, source_state: str, recognized: bool, target_roi=None) -> None:
        if not isinstance(self.runtime, NavigationGuardedRuntime):
            raise NavigationBoundaryError("navigation firewall required before transport")
        # Adapter supplies recognition facts only; live package/device/profile/dims bind at dispatch.
        facts = make_source_safety_facts(
            recognized=recognized,
            source_state=source_state,
            overlay_state="none_observed",
            frame_sha256=captured.sha256,
            captured_monotonic=captured.captured_monotonic,
            target_roi=target_roi,
        )
        self.runtime.prepare_source_safety(facts)

    def _blocked(self, reason: str, *, terminal_home: bool = False) -> NoahTavernNavigationResult:
        return NoahTavernNavigationResult(
            "blocked",
            reason,
            self.input_count,
            0,
            terminal_home,
            tuple(self.records),
            str(self.runtime.session),
        )

    def _runtime_is_live(self) -> bool:
        runtime = self.runtime
        if isinstance(runtime, NavigationGuardedRuntime):
            runtime = runtime._inner
        return hasattr(runtime, "runner")

    def _atlas_binding(self, captured: CapturedNativeFrame):
        """Bind Noah's Tavern from the current canonical Home Atlas frame only."""

        if not self._runtime_is_live() and not self._home_localizer_injected:
            return None
        try:
            localization = self.home_localizer.localize(captured.frame)
        except (OSError, ValueError, TypeError):
            return None
        if (
            not localization.recognized
            or localization.zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT
            or localization.frame_sha256 != frame_digest(captured.frame)
        ):
            return None
        binding = bind_visible_building(
            captured.frame,
            localization,
            self.atlas.lookup_building(NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID),
            ocr=_noahs_tavern_binding_ocr,
        )
        if (
            binding is None
            or binding.building_id != NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID
            or binding.frame_sha256 != frame_digest(captured.frame)
            or binding.confidence < 0.80
            or not binding.semantic_evidence
            or binding.overlay_intersects
            or binding.ambiguous_overlap
        ):
            return None
        return tuple(binding.target_roi)

    def _canonical_home_proven(self, captured: CapturedNativeFrame, observation) -> bool:
        """Require canonical Home Atlas proof after the safe Tavern exit."""

        if getattr(observation, "recognized", False) and getattr(observation, "screen_state", None) != HOME_BASE_SCREEN:
            return False
        if (
            not self._runtime_is_live()
            and not self._home_localizer_injected
            and getattr(observation, "screen_state", None) == HOME_BASE_SCREEN
        ):
            return True
        try:
            localization = self.home_localizer.localize(captured.frame)
        except (OSError, ValueError, TypeError):
            localization = None
        if (
            localization is not None
            and localization.recognized
            and localization.zoom_identity is ZoomIdentity.FULLY_ZOOMED_OUT
            and localization.frame_sha256 == frame_digest(captured.frame)
        ):
            return True
        # Scripted offline route seams use black frames and inject semantic Home
        # observations.  They cannot be mistaken for production because a live
        # LocalBlueStacksRuntime always exposes its ADB runner.
        return bool(not self._runtime_is_live() and getattr(observation, "screen_state", None) == HOME_BASE_SCREEN)

    @staticmethod
    def _positive_source_state(observation) -> tuple[str, bool]:
        """Return the positively measured navigation surface; never promote from allowlist."""

        overlay = str(getattr(observation, "overlay_state", "none") or "none").strip().casefold()
        if observation.stale or not observation.recognized:
            return observation.screen_state, False
        if overlay not in {"none", "none_observed"}:
            return observation.screen_state, False
        if observation.screen_state in {HOME_BASE_SCREEN, NOAHS_TAVERN_SCREEN}:
            return observation.screen_state, True
        return observation.screen_state, False

    def _return_home(self, captured: CapturedNativeFrame, observation) -> NoahTavernNavigationResult:
        if self._canonical_home_proven(captured, observation):
            return NoahTavernNavigationResult(
                "completed",
                "verified_safe_return_home",
                self.input_count,
                0,
                True,
                tuple(self.records),
                str(self.runtime.session),
            )
        # Exactly one safe exit is authorized.  It is bound to a fresh, positively
        # recognized Tavern frame and must be followed by canonical Home proof.
        if self.maximum_return_inputs < 1:
            return self._blocked("safe_exit_budget_exhausted")
        state, ok = self._positive_source_state(observation)
        if not ok or state != NOAHS_TAVERN_SCREEN:
            return self._blocked("return_source_not_recognized")
        immediate_before = self._capture("tavern-safe-exit-immediate-before")
        rebound = self._recognize(immediate_before)
        rebound_state, rebound_ok = self._positive_source_state(rebound)
        if not rebound_ok or rebound_state != NOAHS_TAVERN_SCREEN:
            return self._blocked("return_source_revalidation_failed")
        self._prepare(immediate_before, source_state=NOAHS_TAVERN_SCREEN, recognized=True)
        self.runtime.back(
            immediate_before,
            action_key=f"noah-nav:safe-exit:{immediate_before.sha256}",
            target_identity=NOAHS_TAVERN_SAFE_EXIT_TARGET,
        )
        immediate_post, settled = self._settle(
            "tavern-safe-exit-immediate-post",
            "tavern-safe-exit-settled",
        )
        successor = self._recognize(settled)
        self._record_input(
            "safe_exit_to_canonical_home",
            immediate_before,
            settled,
            target_identity=NOAHS_TAVERN_SAFE_EXIT_TARGET,
            successor_state=getattr(successor, "screen_state", "UNKNOWN"),
            immediate_post_sha256=immediate_post.sha256,
        )
        if not self._canonical_home_proven(settled, successor):
            return self._blocked("safe_exit_canonical_home_not_proven")
        return NoahTavernNavigationResult(
            "completed",
            "verified_safe_return_home",
            self.input_count,
            0,
            True,
            tuple(self.records),
            str(self.runtime.session),
        )

    def run(self) -> NoahTavernNavigationResult:
        source, observation = self._observe("tavern-canary-source")
        for step in range(1, self.maximum_steps + 1):
            state, ok = self._positive_source_state(observation)
            if not ok and self._canonical_home_proven(source, observation):
                state, ok = HOME_BASE_SCREEN, True
            if not ok:
                return self._blocked(
                    "unknown_or_overlaid_source_state"
                    if observation.recognized
                    else "source_state_not_recognized"
                )
            if state == HOME_BASE_SCREEN:
                immediate_before = self._capture(f"tavern-open-{step:02d}-immediate-before")
                rebound = self._recognize(immediate_before)
                atlas_home = self._canonical_home_proven(immediate_before, rebound)
                if (
                    (not rebound.recognized and not atlas_home)
                    or rebound.stale
                    or (rebound.recognized and rebound.screen_state != HOME_BASE_SCREEN)
                ):
                    if (
                        rebound.recognized
                        and rebound.screen_state == HOME_BASE_SCREEN
                        and rebound.home_tavern_target_roi is None
                        and self._runtime_is_live()
                    ):
                        # Atlas binding below is the sole production entry authority.
                        pass
                    elif rebound.recognized and rebound.screen_state == HOME_BASE_SCREEN:
                        pass
                    else:
                        return self._blocked("home_tavern_open_revalidation_failed")
                target_roi = self._atlas_binding(immediate_before)
                if target_roi is None and not self._runtime_is_live():
                    # Offline scripted seam: production uses only the Atlas binding;
                    # black synthetic frames retain the existing task-specific ROI.
                    target_roi = rebound.home_tavern_target_roi
                if target_roi is None:
                    return self._blocked("home_tavern_target_not_current_frame_bound")
                self._prepare(
                    immediate_before,
                    source_state=HOME_BASE_SCREEN,
                    recognized=True,
                    target_roi=target_roi,
                )
                self.runtime.tap(
                    immediate_before,
                    target_identity=NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID,
                    target_roi=target_roi,
                    action_key=f"noah-nav:open-tavern:{immediate_before.sha256}",
                    consequential=False,
                )
                _immediate_post, settled = self._settle(
                    f"tavern-open-{step:02d}-immediate-post",
                    f"tavern-open-{step:02d}-settled",
                )
                self._record_input("tap_tavern_navigation", immediate_before, settled)
                observation = self._recognize(settled)
                continue
            if state == NOAHS_TAVERN_SCREEN:
                # Navigation goal reached; the recruit endpoint is intentionally excluded.
                return self._return_home(source, observation)
            return self._blocked("unexpected_navigation_state")
        return self._blocked("maximum_navigation_steps")


def run_noahs_tavern_navigation_canary(args, identity=None) -> str:
    """Checked-in pnsctl live runner for the navigation-only Tavern canary.

    ``identity`` is accepted for runner-signature symmetry with the Nova canary; this
    navigation-only route needs no account/server/reset identity.
    """

    runtime = LocalBlueStacksRuntime.connect(
        adb=str(args.adb),
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="noahs-tavern-navigation-canary",
        execute=True,
    )


    if getattr(args, "safe_exit_only", False):
        runtime.max_inputs = min(runtime.max_inputs, 1)
        route = NoahTavernNavigationCanaryRoute(
            runtime,
            settle_seconds=getattr(args, "settle_seconds", 1.0),
            route_declaration=noahs_tavern_navigation_route_declaration(),
        )
        source, observation = route._observe("tavern-safe-exit-only-source")
        result = route._return_home(source, observation)
        payload = {
            "status": result.status,
            "reason": result.reason,
            "navigation_input_count": result.navigation_input_count,
            "recruit_taps": 0,
            "terminal_home_verified": result.terminal_home_verified,
            "records": result.records,
            "session_directory": result.session,
        }
        (runtime.session / "safe-exit-only-result.json").write_text(
            json.dumps(payload, sort_keys=True, default=str, indent=2) + "\n", encoding="utf-8"
        )
        return json.dumps(payload, sort_keys=True, default=str)

    # This migration has exactly two authorized navigation inputs: Atlas-bound
    # Tavern entry and one positively recognized Tavern safe exit.
    runtime.max_inputs = min(runtime.max_inputs, 2)
    route = NoahTavernNavigationCanaryRoute(
        runtime,
        settle_seconds=getattr(args, "settle_seconds", 1.0),
        route_declaration=noahs_tavern_navigation_route_declaration(),
    )
    result = None
    try:
        result = route.run()
    except BaseException as exc:
        finalize_navigation_evidence(
            runtime.session,
            status="failed",
            reason=f"exception:{type(exc).__name__}",
            records=tuple(route.records),
            flow_id=NOAHS_TAVERN_NAV_FLOW_ID,
            scenario_id=NOAHS_TAVERN_NAV_SCENARIO_ID,
            navigation_input_count=route.input_count,
            authorized_gestures=(
                route.runtime.authorized_gestures
                if isinstance(route.runtime, NavigationGuardedRuntime)
                else ()
            ),
            extra={
                "recruit_taps": 0,
                "terminal_home_verified": False,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
            },
            exception=exc,
        )
        raise
    finalize_navigation_evidence(
        runtime.session,
        status=result.status
        if result.status in {"completed", "blocked", "manual_required", "unresolved", "failed"}
        else "blocked",
        reason=result.reason,
        records=result.records,
        flow_id=NOAHS_TAVERN_NAV_FLOW_ID,
        scenario_id=NOAHS_TAVERN_NAV_SCENARIO_ID,
        navigation_input_count=result.navigation_input_count,
        authorized_gestures=(
            route.runtime.authorized_gestures
            if isinstance(route.runtime, NavigationGuardedRuntime)
            else ()
        ),
        extra={
            "recruit_taps": result.recruit_taps,
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
            "scenario_id": NOAHS_TAVERN_NAV_SCENARIO_ID,
            "session_directory": str(runtime.session),
            "navigation_input_count": result.navigation_input_count,
            "recruit_taps": result.recruit_taps,
            "transport_calls": result.navigation_input_count,
            "terminal_home_verified": result.terminal_home_verified,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        },
        sort_keys=True,
    )


def run_noahs_tavern_unified_recruitment(args, identity: SchedulerIdentity | None = None) -> str:
    """Run one bounded native unified Basic/Int./Advanced recruitment pass.

    Recruitment is ordinary development interaction: the runtime retains native capture and
    dispatch evidence but no consequential lifecycle or action journal is created. The existing
    scheduler invocation repository stores verified maintenance progress only.
    """

    if identity is None:
        raise ValueError("unified recruitment requires one established game-day identity")
    from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository
    from scripts.home_atlas_bluestacks import (
        BlueStacksLocalizeFirstHomeDriver,
        ScrcpyMotionEventZoomTransport,
    )
    from scripts.navigation_development_boundary import NavigationGuardedRuntime, make_source_safety_facts
    from tasks.home_atlas import load_home_atlas
    from tasks.home_context import HomeReadyObservation
    from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity
    import cv2

    runtime = LocalBlueStacksRuntime.connect(
        adb=str(args.adb),
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="noahs-tavern-unified-recruitment",
        execute=True,
    )
    runtime.max_inputs = min(runtime.max_inputs, int(getattr(args, "max_inputs", 12)))
    if runtime.max_inputs < 12:
        raise ValueError("unified recruitment requires a twelve-input total session cap")
    zoom_records: list[dict[str, object]] = []
    atlas_path = NOAHS_TAVERN_HOME_ATLAS_PATH
    atlas = load_home_atlas(atlas_path)
    verified_identity = VerifiedRuntimeIdentity(
        "bluestacks-unified-recruitment",
        identity.account_id,
        identity.server_id,
        identity.reset_id,
        RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        (f"session:{runtime.session}", "pnsctl:unified-recruitment"),
    )
    home_driver = BlueStacksLocalizeFirstHomeDriver(
        atlas,
        atlas_path,
        HomeReadyObservation(True, True, verified_identity, False, False),
        NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID,
        maximum_zoom_inputs=2,
    )
    zoom_guard = NavigationGuardedRuntime(
        runtime,
        NavigationRouteDeclaration(
            allowed_source_states=frozenset({HOME_BASE_SCREEN}),
            allowed_target_identities=frozenset({"home-zoom-out", "home-camera-click-drag"}),
            allowed_gesture_classes=frozenset({"zoom_out", "swipe"}),
        ),
    )
    # The runtime's sequential virtual-touch pinch can report success without changing
    # this game's camera. Use scrcpy's control socket to inject simultaneous pointers.
    native_zoom = ScrcpyMotionEventZoomTransport(
        adb=str(args.adb),
        serial=args.serial,
        evidence_directory=runtime.session,
    )
    # Two zoom inputs plus up to two evidence-driven Atlas pans. In the common
    # already-zoomed-out case this executes only the single required pan.
    for ordinal in range(1, 5):
        source = runtime.capture(f"home-zoom-normalization-{ordinal:02d}-immediate-before")
        source_home_recognized, source_home_facts = recognize_home_zoom_source(source.frame)
        step = home_driver.observe(source.frame)
        source_screen = recognize_noahs_tavern_frame(
            source.frame, captured_monotonic=source.captured_monotonic
        )
        atlas_canonical_home = _atlas_canonical_home(step.localization, source_screen)
        if not source_home_recognized and not atlas_canonical_home:
            raise RuntimeError("home zoom normalization requires positively recognized Home source")
        row: dict[str, object] = {
            "ordinal": ordinal,
            "disposition": step.disposition.value,
            "reason": step.reason,
            "source_sha256": source.sha256,
            "zoom_identity": step.localization.zoom_identity.value,
            "home_ready_recognized": source_home_recognized,
            "atlas_canonical_home": atlas_canonical_home,
        }
        if step.disposition.value in {"complete", "bind"}:
            zoom_records.append(row)
            break
        if step.disposition.value == "blocked":
            raise RuntimeError(f"home zoom normalization blocked: {step.reason}")
        facts = make_source_safety_facts(
            recognized=True,
            source_state=HOME_BASE_SCREEN,
            overlay_state="none_observed",
            frame_sha256=source.sha256,
            captured_monotonic=source.captured_monotonic,
        )
        if step.disposition.value == "pan":
            plan = step.plan
            if plan is None or plan.drag_start is None or plan.drag_end is None:
                raise RuntimeError("home Atlas pan geometry is missing")
            zoom_guard.prepare_source_safety(facts)
            zoom_guard.swipe(
                source,
                start=plan.drag_start,
                end=plan.drag_end,
                action_key=f"noah:home-pan:{ordinal}:{source.sha256}",
                target_identity="home-camera-click-drag",
            )
            immediate_post = runtime.capture(f"home-pan-{ordinal:02d}-immediate-post")
            if getattr(args, "settle_seconds", 1.0) > 0:
                time.sleep(getattr(args, "settle_seconds", 1.0))
            settled = runtime.capture(f"home-pan-{ordinal:02d}-settled")
            settled_home_recognized, settled_home_facts = recognize_home_zoom_source(settled.frame)
            after_localization = home_driver.localizer.localize(settled.frame)
            settled_observation = recognize_noahs_tavern_frame(
                settled.frame, captured_monotonic=settled.captured_monotonic
            )
            settled_atlas_home = _atlas_canonical_home(after_localization, settled_observation)
            if not settled_home_recognized and not settled_atlas_home:
                raise RuntimeError("home Atlas pan successor Home state was not positively recognized")
            progress = home_driver.record_pan_progress(step.localization, after_localization)
            row.update(
                {
                    "action": "bounded_home_pan",
                    "drag_start": list(plan.drag_start),
                    "drag_end": list(plan.drag_end),
                    "immediate_post_sha256": immediate_post.sha256,
                    "settled_sha256": settled.sha256,
                    "settled_home_facts": settled_home_facts,
                    "settled_atlas_canonical_home": settled_atlas_home,
                    "progress_accepted": progress.accepted,
                    "progress_reason": progress.reason,
                }
            )
            zoom_records.append(row)
            if not progress.accepted:
                raise RuntimeError(f"home Atlas pan made no measured progress: {progress.reason}")
            continue
        if step.disposition.value != "recover_zoom":
            raise RuntimeError(f"unsupported Home Atlas recovery disposition: {step.disposition.value}")
        try:
            zoom_guard.dispatch_zoom_out(
                source,
                facts,
                transport=native_zoom.zoom_out_once,
                target_identity="home-zoom-out",
            )
            # The Home driver plans against its semantic pixel digest, while runtime evidence
            # uses the retained PNG-byte digest.  Pass the planner's own digest to avoid a
            # false current-frame mismatch after a successfully dispatched zoom.
            record_home_zoom_recovery_input(home_driver, step)
            immediate_post = runtime.capture(f"home-zoom-normalization-{ordinal:02d}-immediate-post")
            if getattr(args, "settle_seconds", 1.0) > 0:
                time.sleep(getattr(args, "settle_seconds", 1.0))
            settled = runtime.capture(f"home-zoom-normalization-{ordinal:02d}-settled")
            immediate_observation = recognize_noahs_tavern_frame(
                immediate_post.frame, captured_monotonic=immediate_post.captured_monotonic
            )
            settled_observation = recognize_noahs_tavern_frame(
                settled.frame, captured_monotonic=settled.captured_monotonic
            )
            immediate_home_recognized, immediate_home_facts = recognize_home_zoom_source(immediate_post.frame)
            settled_home_recognized, settled_home_facts = recognize_home_zoom_source(settled.frame)
            if settled.sha256 == source.sha256:
                raise RuntimeError("home zoom normalization produced no measured frame progress")
            settled_localization = home_driver.localizer.localize(settled.frame)
            settled_atlas_home = _atlas_canonical_home(settled_localization, settled_observation)
            if not settled_home_recognized and not settled_atlas_home:
                raise RuntimeError("home zoom normalization successor Home state was not positively recognized")
            row.update(
                {
                    "immediate_post_sha256": immediate_post.sha256,
                    "immediate_post_screen_state": immediate_observation.screen_state,
                    "immediate_post_recognized": immediate_observation.recognized,
                    "settled_sha256": settled.sha256,
                    "settled_screen_state": settled_observation.screen_state,
                    "settled_recognized": settled_observation.recognized,
                    "source_home_facts": source_home_facts,
                    "immediate_home_recognized": immediate_home_recognized,
                    "immediate_home_facts": immediate_home_facts,
                    "settled_home_recognized": settled_home_recognized,
                    "settled_home_facts": settled_home_facts,
                    "settled_atlas_canonical_home": settled_atlas_home,
                }
            )
            zoom_records.append(row)
        except Exception as exc:
            row["exception"] = f"{type(exc).__name__}: {exc}"
            # A failed transport can still leave the device changed.  Best-effort captures
            # preserve immediate-post/settled evidence without issuing another input.
            for phase, label in (("immediate_post", f"home-zoom-normalization-{ordinal:02d}-immediate-post-error"), ("settled", f"home-zoom-normalization-{ordinal:02d}-settled-error")):
                try:
                    frame = runtime.capture(label)
                    row[f"{phase}_sha256"] = frame.sha256
                    observation = recognize_noahs_tavern_frame(
                        frame.frame, captured_monotonic=frame.captured_monotonic
                    )
                    home_recognized, home_facts = recognize_home_zoom_source(frame.frame)
                    row[f"{phase}_screen_state"] = observation.screen_state
                    row[f"{phase}_recognized"] = observation.recognized
                    row[f"{phase}_home_ready_recognized"] = home_recognized
                    row[f"{phase}_home_ready_facts"] = home_facts
                except Exception as capture_exc:
                    row[f"{phase}_error"] = f"{type(capture_exc).__name__}: {capture_exc}"
            zoom_records.append(row)
            _write_unified_result(
                runtime,
                {
                    "status": "blocked",
                    "reason": "home_zoom_normalization_exception",
                    "failure_stage": "home_zoom_normalization",
                    "error": row["exception"],
                    "actions_completed": 0,
                    "session_directory": str(runtime.session),
                    "input_count": runtime.input_count,
                    "terminal_home_verified": False,
                    "recruitment_dispatch_count": 0,
                    "claim_dispatched": False,
                    "transport_mode": "native_bluestacks_ordinary_development",
                    "identity": identity.__dict__,
                    "production_registration": "NOT_REGISTERED",
                    "scheduler_enabled": False,
                    "evidence_events": str(runtime.events),
                    "zoom_normalization": zoom_records,
                },
            )
            raise
    try:
        atlas_probe = runtime.capture("home-atlas-entry-immediate-before-annotated")
        atlas_route = NoahTavernNavigationCanaryRoute(runtime, settle_seconds=0.0)
        binding = atlas_route._atlas_binding(atlas_probe)
    except Exception as exc:
        _write_unified_result(
            runtime,
            {
                "status": "blocked",
                "reason": "home_atlas_binding_exception",
                "failure_stage": "home_atlas_binding",
                "error": f"{type(exc).__name__}: {exc}",
                "actions_completed": 0,
                "session_directory": str(runtime.session),
                "input_count": runtime.input_count,
                "terminal_home_verified": False,
                "recruitment_dispatch_count": 0,
                "claim_dispatched": False,
                "transport_mode": "native_bluestacks_ordinary_development",
                "identity": identity.__dict__,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
                "evidence_events": str(runtime.events),
                "zoom_normalization": zoom_records,
            },
        )
        raise
    annotated_path = runtime.session / "home-atlas-entry-immediate-before-annotated.png"
    annotated = atlas_probe.frame.copy()
    if binding is None:
        _write_unified_result(
            runtime,
            {
                "status": "blocked",
                "reason": "home_atlas_binding_not_proven",
                "failure_stage": "home_atlas_binding",
                "actions_completed": 0,
                "session_directory": str(runtime.session),
                "input_count": runtime.input_count,
                "terminal_home_verified": False,
                "recruitment_dispatch_count": 0,
                "claim_dispatched": False,
                "transport_mode": "native_bluestacks_ordinary_development",
                "identity": identity.__dict__,
                "production_registration": "NOT_REGISTERED",
                "scheduler_enabled": False,
                "evidence_events": str(runtime.events),
                "zoom_normalization": zoom_records,
            },
        )
        raise RuntimeError("home Atlas binding not proven after bounded zoom normalization")
    x0, y0, x1, y1 = binding
    cv2.rectangle(annotated, (x0, y0), (x1, y1), (0, 255, 0), 4)
    cv2.putText(annotated, NOAHS_TAVERN_HOME_ATLAS_BUILDING_ID, (x0, max(30, y0 - 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)
    cv2.imwrite(str(annotated_path), annotated)
    zoom_records.append({"atlas_probe_sha256": atlas_probe.sha256, "atlas_binding_roi": list(binding), "annotated_frame": str(annotated_path)})
    runtime.max_inputs = min(runtime.max_inputs, runtime.input_count + 10)
    store = SafetyStore(runtime.session / "maintenance-state.sqlite3")
    repository = SQLiteSchedulerInvocationRepository(store)
    try:
        invocation = repository.get(identity)
        state_session = getattr(args, "state_session", None)
        if state_session is not None:
            prior_path = Path(state_session) / "maintenance-state.sqlite3"
            if not prior_path.is_file():
                raise ValueError("state session has no persisted maintenance state")
            prior_store = SafetyStore(prior_path)
            try:
                prior_invocation = SQLiteSchedulerInvocationRepository(prior_store).get(identity)
                if prior_invocation is None:
                    raise ValueError("state session has no matching scheduler identity")
                state = NoahMaintenanceState.from_scheduler_invocation(prior_invocation)
            finally:
                prior_store.close()
        else:
            state = NoahMaintenanceState.from_scheduler_invocation(invocation) if invocation else NoahMaintenanceState.for_identity(identity)
        controller = NoahTavernRecruitRuntimeController(
            now=time.time(),
            maintenance_state=state,
            repository=repository,
            scheduler_identity=identity,
        )
        route = NoahTavernIntegratedRoute(
            runtime,
            max_recruits=3,
            controller=controller,
            post_input_delay=getattr(args, "settle_seconds", 1.0),
        )
        result = route.run(max_steps=40)
        payload = {
            "status": result.status,
            "reason": result.reason,
            "actions_completed": result.actions_completed,
            "session_directory": str(runtime.session),
            "input_count": runtime.input_count,
            "terminal_home_verified": result.status == "completed" and result.reason == "verified_safe_return_home",
            "recruitment_dispatch_count": result.actions_completed,
            "claim_dispatched": False,
            "transport_mode": "native_bluestacks_ordinary_development",
            "identity": identity.__dict__,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
            "evidence_events": str(runtime.events),
            "zoom_normalization": zoom_records,
            "atlas_binding_roi": list(binding),
            "atlas_immediate_before_sha256": atlas_probe.sha256,
            "atlas_annotated_frame": str(annotated_path),
        }
        (runtime.session / "unified-recruitment-result.json").write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        return json.dumps(payload, sort_keys=True)
    finally:
        store.close()


def run_noahs_tavern_recruitment_continuation(args, identity: SchedulerIdentity | None = None) -> str:
    """Continue only remaining eligible tiers from an already-open retained Tavern state."""

    if identity is None:
        raise ValueError("recruitment continuation requires one established game-day identity")
    prior_session = Path(args.continuation_session)
    prior_store_path = prior_session / "maintenance-state.sqlite3"
    if not prior_store_path.is_file():
        raise ValueError("continuation session has no persisted maintenance state")
    from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository

    prior_store = SafetyStore(prior_store_path)
    try:
        prior_repo = SQLiteSchedulerInvocationRepository(prior_store)
        invocation = prior_repo.get(identity)
        if invocation is None:
            raise ValueError("continuation session has no matching scheduler identity")
        state = NoahMaintenanceState.from_scheduler_invocation(invocation)
    finally:
        prior_store.close()

    runtime = LocalBlueStacksRuntime.connect(
        adb=str(args.adb), serial=args.serial, output_directory=args.output_directory,
        workflow="noahs-tavern-unified-recruitment-continuation", execute=True,
    )
    # From an arbitrary current Tavern tab: one tier selection, one free recruit,
    # one result close, and one positively recognized safe exit.
    runtime.max_inputs = min(runtime.max_inputs, 4)
    current = runtime.capture("continuation-tavern-source")
    observation = recognize_noahs_tavern_frame(
        current.frame, captured_monotonic=current.captured_monotonic
    )
    if observation.screen_state != NOAHS_TAVERN_SCREEN or not observation.recognized:
        payload = {
            "status": "blocked", "reason": "continuation_tavern_source_not_recognized",
            "session_directory": str(runtime.session), "input_count": 0,
            "recruitment_dispatch_count": 0, "claim_dispatched": False,
            "terminal_home_verified": False, "continuation_of": str(prior_session),
        }
        return _write_unified_result(runtime, payload)

    store = SafetyStore(runtime.session / "maintenance-state.sqlite3")
    repository = SQLiteSchedulerInvocationRepository(store)
    try:
        controller = NoahTavernRecruitRuntimeController(
            now=current.captured_monotonic,
            maintenance_state=state,
            repository=repository,
            scheduler_identity=identity,
        )
        route = NoahTavernIntegratedRoute(
            runtime, max_recruits=1, controller=controller,
            post_input_delay=getattr(args, "settle_seconds", 1.0),
        )
        result = route.run(max_steps=12)
        final_state = controller.maintenance_controller.state
        payload = {
            "status": result.status,
            "reason": result.reason,
            "actions_completed": result.actions_completed,
            "session_directory": str(runtime.session),
            "input_count": runtime.input_count,
            "terminal_home_verified": result.status == "completed" and result.reason == "verified_safe_return_home",
            "recruitment_dispatch_count": result.actions_completed,
            "claim_dispatched": False,
            "continuation_of": str(prior_session),
            "identity": identity.__dict__,
            "maintenance_state": json.loads(final_state.to_json()),
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
            "evidence_events": str(runtime.events),
        }
        return _write_unified_result(runtime, payload)
    finally:
        store.close()


def reconcile_noahs_tavern_retained_recruit(args, identity: SchedulerIdentity | None = None) -> str:
    """Reconcile one retained free recruit and canonical Home with zero runtime input."""

    if identity is None:
        raise ValueError("retained recruitment reconciliation requires one game-day identity")
    from safe_action_core import SafetyStore, SQLiteSchedulerInvocationRepository

    prior_session = Path(args.state_session)
    evidence_session = Path(args.reconcile_session)
    terminal_session = Path(args.terminal_home_session)
    prior_path = prior_session / "maintenance-state.sqlite3"
    if not prior_path.is_file():
        raise ValueError("state session has no persisted maintenance state")
    before_path = evidence_session / "frames" / "0002-step-001-source.png"
    result_path = evidence_session / "frames" / "0003-recruit-immediate-post.png"
    after_path = evidence_session / "frames" / "0005-recruit-after-close.png"
    terminal_path = terminal_session / "frames" / "0004-tavern-safe-exit-settled.png"
    for path in (before_path, result_path, after_path, terminal_path):
        if not path.is_file():
            raise ValueError(f"required retained frame is missing: {path}")
    before = recognize_noahs_tavern_frame(read_frame(before_path), captured_monotonic=time.monotonic())
    result = recognize_noahs_tavern_frame(read_frame(result_path), captured_monotonic=time.monotonic())
    after = recognize_noahs_tavern_frame(read_frame(after_path), captured_monotonic=time.monotonic())
    if before.screen_state != NOAHS_TAVERN_SCREEN or before.selected_tier is not RecruitTier.ADV or not before.recognized:
        raise ValueError("retained Advanced source is not positively recognized")
    if result.screen_state != HERO_RECRUIT_RESULT_SCREEN or not result.recognized:
        raise ValueError("retained Advanced result is not positively recognized")
    if after.screen_state != NOAHS_TAVERN_SCREEN or after.selected_tier is not RecruitTier.ADV or not after.recognized:
        raise ValueError("retained Advanced post-close cooldown is not positively recognized")
    terminal_frame = read_frame(terminal_path)
    terminal_observation = recognize_noahs_tavern_frame(terminal_frame, captured_monotonic=time.monotonic())
    atlas = load_home_atlas(NOAHS_TAVERN_HOME_ATLAS_PATH)
    localization = BlueStacksHomeLocalizer(atlas, NOAHS_TAVERN_HOME_ATLAS_PATH).localize(terminal_frame)
    if (
        terminal_observation.recognized
        and terminal_observation.screen_state != HOME_BASE_SCREEN
    ) or not localization.recognized or localization.zoom_identity is not ZoomIdentity.FULLY_ZOOMED_OUT:
        raise ValueError("retained terminal frame is not canonical Home")

    prior_store = SafetyStore(prior_path)
    try:
        invocation = SQLiteSchedulerInvocationRepository(prior_store).get(identity)
        if invocation is None:
            raise ValueError("state session has no matching scheduler identity")
        state = NoahMaintenanceState.from_scheduler_invocation(invocation)
    finally:
        prior_store.close()
    if state.tiers[RecruitTier.ADV].last_outcome == "action_performed":
        raise ValueError("retained Advanced recruit is already reconciled")

    session = Path(args.output_directory) / f"noahs-tavern-retained-reconcile-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    session.mkdir(parents=True, exist_ok=False)
    store = SafetyStore(session / "maintenance-state.sqlite3")
    repository = SQLiteSchedulerInvocationRepository(store)
    try:
        controller = NoahTavernRecruitRuntimeController(
            now=time.monotonic(), maintenance_state=state, repository=repository, scheduler_identity=identity
        )
        controller.progress.awaiting_postcondition = True
        controller.progress.awaiting_tier = RecruitTier.ADV
        controller.progress.awaiting_before = before
        controller._remember_tier(before, RecruitTier.ADV)
        wrapped_result = NoahTavernIntegratedRoute._wrap(replace(result, result_tier=RecruitTier.ADV))
        if not controller.accept_postcondition(wrapped_result, after):
            raise ValueError("retained Advanced result/cooldown postcondition is not proven")
        state = controller.maintenance_controller.state
        payload = {
            "status": "completed",
            "reason": "retained_advanced_free_recruit_and_terminal_home_reconciled",
            "transport_calls": 0,
            "claim_dispatched": False,
            "terminal_home_verified": True,
            "identity": identity.__dict__,
            "maintenance_state": json.loads(state.to_json()),
            "state_session": str(session),
            "evidence_session": str(evidence_session),
            "terminal_home_session": str(terminal_session),
            "source_frame": str(before_path),
            "result_frame": str(result_path),
            "post_close_frame": str(after_path),
            "terminal_home_frame": str(terminal_path),
            "terminal_home_semantic_sha256": localization.frame_sha256,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        }
        (session / "retained-reconciliation-result.json").write_text(
            json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8"
        )
        return json.dumps(payload, sort_keys=True, default=str)
    finally:
        store.close()


def run_noahs_tavern_recruitment_preflight(args) -> str:
    """Capture one current native source frame without input for unified recruitment preflight."""

    runtime = LocalBlueStacksRuntime.connect(
        adb=str(args.adb),
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="noahs-tavern-unified-recruitment-preflight",
        execute=False,
    )
    source = runtime.capture("unified-recruitment-preflight-source")
    observation = recognize_noahs_tavern_frame(source.frame, captured_monotonic=source.captured_monotonic)
    payload = {
        "status": "preflight_passed" if observation.recognized else "blocked",
        "reason": "current_source_recognized" if observation.recognized else "current_source_not_recognized",
        "source_frame": str(source.path),
        "source_frame_sha256": source.sha256,
        "screen_state": observation.screen_state,
        "selected_tier": observation.selected_tier.name if observation.selected_tier else None,
        "tier_observations": {
            tier.name: {
                "recognized": observation.tier(tier).recognized,
                "attempts_remaining": observation.tier(tier).attempts_remaining,
                "cooldown_active": observation.tier(tier).cooldown_active,
                "next_eligible_timestamp": observation.tier(tier).next_eligible_timestamp,
                "free_control_enabled": observation.tier(tier).free_control_enabled,
            }
            for tier in RecruitTier
        },
        "input_count": 0,
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
        "session_directory": str(runtime.session),
    }
    (runtime.session / "unified-recruitment-preflight-result.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return json.dumps(payload, sort_keys=True)


def run_noahs_tavern_recovery_continuation(args, identity=None) -> str:
    """Continue one retained Tavern screen, then prove a fresh canonical round trip.

    The recovery prelude is explicitly separated from the new proof records and is capped at
    three total navigation inputs (one recovery exit plus two fresh round-trip inputs).
    """

    runtime = LocalBlueStacksRuntime.connect(
        adb=str(args.adb), serial=args.serial, output_directory=args.output_directory,
        workflow="noahs-tavern-recovery-continuation", execute=True,
    )
    runtime.max_inputs = min(runtime.max_inputs, 3)
    route = NoahTavernNavigationCanaryRoute(runtime, settle_seconds=getattr(args, "settle_seconds", 1.0))
    records: list[dict[str, object]] = []
    source, observation = route._observe("recovery-prelude-source")
    if observation.screen_state != NOAHS_TAVERN_SCREEN or not observation.recognized:
        result = {"status": "blocked", "reason": "recovery_tavern_source_not_recognized", "navigation_input_count": 0, "recruit_taps": 0, "terminal_home_verified": False, "recovery_records": [], "proof_records": [], "session_directory": str(runtime.session)}
        (runtime.session / "continuation-result.json").write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        return json.dumps(result, sort_keys=True)
    recovery = route._return_home(source, observation)
    records.extend({**item, "phase": "recovery_prelude"} for item in recovery.records)
    if recovery.status != "completed" or not recovery.terminal_home_verified:
        result = {"status": "blocked", "reason": "recovery_prelude_home_not_proven", "navigation_input_count": recovery.navigation_input_count, "recruit_taps": 0, "terminal_home_verified": False, "recovery_records": records, "proof_records": [], "session_directory": str(runtime.session)}
        (runtime.session / "continuation-result.json").write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        return json.dumps(result, sort_keys=True)
    proof = NoahTavernNavigationCanaryRoute(runtime, settle_seconds=getattr(args, "settle_seconds", 1.0), maximum_return_inputs=1)
    proof_result = proof.run()
    proof_records = [{**item, "phase": "canonical_round_trip"} for item in proof_result.records]
    proof_actions = [str(item.get("action")) for item in proof_records]
    proof_complete = (
        proof_result.status == "completed"
        and proof_result.terminal_home_verified
        and proof_result.navigation_input_count == 2
        and proof_actions == ["tap_tavern_navigation", "safe_exit_to_canonical_home"]
    )
    result = {
        "status": "completed" if proof_complete else "blocked",
        "reason": proof_result.reason if proof_complete else "canonical_round_trip_proof_incomplete",
        "navigation_input_count": recovery.navigation_input_count + proof_result.navigation_input_count,
        "recruit_taps": 0,
        "terminal_home_verified": bool(proof_complete),
        "recovery_records": records,
        "proof_records": proof_records,
        "session_directory": str(runtime.session),
    }
    (runtime.session / "continuation-result.json").write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    return json.dumps(result, sort_keys=True)


def read_frame(path: Path):
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cannot read native BlueStacks frame: {path}")
    if frame.shape[:2] != (1280, 800):
        raise ValueError("BlueStacks frame must be native 800x1280")
    return frame


def load_unresolved_recruit(session: Path) -> tuple[Path, Path, str, RecruitTier]:
    events_path = session / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    unresolved = next((event for event in reversed(events) if event.get("type") == "reconcile" and event.get("status") == "unresolved"), None)
    if unresolved is None:
        raise RuntimeError("session has no unresolved recruit action")
    action_key = str(unresolved["action_key"])
    dispatch = next((event for event in events if event.get("type") == "dispatch" and event.get("action_key") == action_key and event.get("consequential") is True), None)
    if dispatch is None:
        raise RuntimeError("unresolved action has no retained consequential dispatch")
    source_hash = str(dispatch["source_sha256"])
    capture = next((event for event in events if event.get("type") == "capture" and event.get("sha256") == source_hash), None)
    if capture is None:
        raise RuntimeError("unresolved action source frame is missing")
    result_path = Path(str(unresolved["post_path"]))
    tier_name = action_key.split(":", 1)[0]
    try:
        tier = RecruitTier[tier_name]
    except KeyError as exc:
        raise RuntimeError("unresolved action tier is unknown") from exc
    source_path = Path(str(capture["path"]))
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    if not result_path.is_absolute():
        result_path = ROOT / result_path
    return source_path, result_path, action_key, tier


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--max-recruits", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm the exact local BlueStacks target non-interactively")
    parser.add_argument("--resume-unresolved-session", type=Path)
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/noahs-tavern-integrated"))
    args = parser.parse_args(argv)
    if args.execute and not args.yes:
        parser.error("--execute requires --yes")
    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="noahs-tavern",
        execute=args.execute,
    )
    route = NoahTavernIntegratedRoute(runtime, max_recruits=args.max_recruits)
    if args.resume_unresolved_session is not None:
        before_frame, result_frame, action_key, tier = load_unresolved_recruit(args.resume_unresolved_session)
        result = route.resume_unresolved_result(before_frame=before_frame, result_frame=result_frame, action_key=action_key, tier=tier)
    else:
        result = route.run()
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0 if result.status in {"completed", "dry-run"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
