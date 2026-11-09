#!/usr/bin/env python3
"""Canonical service native driver for the fixed Ruins Challenge route."""

from __future__ import annotations


from dataclasses import replace
import re
import hashlib
import json
from pathlib import Path
import time
from typing import Callable

from safe_action_core import Observation
from automation_service.native_execution import NativeRouteBoundary
from scripts.bluestacks_native_runtime import CapturedNativeFrame, IntegratedRouteResult, NativeRuntimePort
from scripts.home_atlas_bluestacks import BlueStacksLocalizeFirstHomeDriver, HomeDriverDisposition, HomeDriverStep, ScrcpyMotionEventZoomTransport, identity_from_captured
from tasks.home_atlas import load_home_atlas
from tasks.home_atlas_planner import DirectPanPlan
from scripts.startup_normalization import is_clean_home_frame
from tasks.home_atlas_vision import BlueStacksHomeLocalizer, bind_visible_building
from tasks.home_context import HomeReadyObservation
from tasks.ruins_challenge import (
    KNOWN_CHALLENGE_IDENTITIES,
    RUINS_CHALLENGE_DISPATCH_ACTION,
    RUINS_CHALLENGE_RESULT_POSTCONDITION,
    RUINS_CHEST_CLAIM_ACTION,
    RUINS_CHEST_CLAIM_POSTCONDITION,
    RuinsAvailability,
    RuinsChestState,
    RuinsControlState,
    RuinsResult,
    challenge_action_authorized,
    challenge_stage,
    dispatch_authorized,
    result_verified,
    ruins_daily_action_key,
)
from tasks.ruins_challenge_runtime import RuinsRuntimeController
from tasks.ruins_challenge_continuation import make_claim_record, write_continuation
from tasks.ruins_challenge_vision import (
    RuinsFrameRecognition,
    recognize_any_ruins_reward_frame,
    recognize_ruins_detail_with_targets,
    recognize_ruins_frame,
    recognize_ruins_result_with_targets,
    recognize_ruins_reward_frame,
)
from tasks.runtime_identity import VerifiedRuntimeIdentity
from automation_service.registry import (
    RUINS_FLOW_ID,
    RUINS_MAX_INPUTS,
    RUINS_PRODUCT_ID,
    RUINS_PRODUCT_REVISION,
    RUINS_PROFILE_ID,
)
from scripts.navigation_development_boundary import (
    NavigationBoundaryError,
    NavigationGuardedRuntime,
    NavigationRouteDeclaration,
    make_source_safety_facts,
)

ROOT = Path(__file__).resolve().parents[1]


RUINS_HOME_ATLAS_BUILDING_ID = "home.building.ruins"
RUINS_LIST_SCROLL_TARGET = "ruins-list-scroll"
MAXIMUM_RUINS_CHEST_SCROLLS = 3
MAXIMUM_HOME_ZOOM_INPUTS = 2
MAXIMUM_HOME_PAN_INPUTS = 4
RUINS_HOME_PAN_TARGET = "home-camera-click-drag"
_ORDINARY_RUINS_TARGETS = frozenset(
    {"ruins-attack", "ruins-dispatch", "ruins-result-continue", "ruins-reward-claim", "reset-popup-close"}
)
MAX_INPUTS = RUINS_MAX_INPUTS
MAX_ACTIONS = 13


def ruins_challenge_navigation_route_declaration() -> NavigationRouteDeclaration:
    return NavigationRouteDeclaration(
        allowed_source_states=frozenset({"HOME_BASE", "RUINS_CHALLENGE", "RUINS_CHALLENGE_DETAIL", "RUINS_DISPATCH_DETAIL", "RUINS_REWARD_MODAL", "CHAT"}),
        allowed_target_identities=frozenset(
            {RUINS_HOME_ATLAS_BUILDING_ID, RUINS_LIST_SCROLL_TARGET, RUINS_HOME_PAN_TARGET, "home-zoom-out", "system-back"}
        ),
        allowed_gesture_classes=frozenset({"tap", "swipe", "back", "zoom_out"}),
    )


class RuinsIntegratedRoute:
    """Drive the challenge first, then independently ready Ruins chests."""
    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        reset_identity: str,
        current_day: str,
        account_id: str,
        server_id: str,
        runtime_scope: str,
        product_id: str,
        product_revision: str,
        runtime_identity: VerifiedRuntimeIdentity,
        action_executor,
        initial_capture: CapturedNativeFrame | None = None,
        home_driver: BlueStacksLocalizeFirstHomeDriver | None = None,
        zoom_transport=None,
        post_input_delay: float = 1.0,
        recognition_timeout: float = 25.0,
    ) -> None:
        if not reset_identity or current_day not in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}:
            raise ValueError("Ruins route requires the current reset and weekday")
        if not all((account_id, server_id, runtime_scope, product_id, product_revision)):
            raise ValueError("Ruins route requires exact runtime and product identity")
        if not isinstance(runtime_identity, VerifiedRuntimeIdentity) or runtime_identity.runtime_scope != runtime_scope:
            raise ValueError("Ruins route requires the existing verified fixed-backend identity")
        if not runtime_identity.reset_id:
            raise ValueError("Ruins route requires the verified backend reset identity")
        if not callable(getattr(action_executor, "status", None)) or not callable(
            getattr(action_executor, "execute", None)
        ):
            raise ValueError("Ruins gameplay requires the canonical action executor")
        declaration = ruins_challenge_navigation_route_declaration()
        if zoom_transport is None and getattr(runtime, "execute", False):
            runner = getattr(runtime, "runner", None)
            if runner is not None:
                zoom_transport = ScrcpyMotionEventZoomTransport(
                    adb=runner.executable,
                    serial=runner.serial,
                    evidence_directory=getattr(runtime, "session", None),
                )
        self.runtime: NativeRuntimePort = (
            runtime if isinstance(runtime, NavigationGuardedRuntime)
            else NavigationGuardedRuntime(runtime, declaration)
        )
        self.reset_identity = reset_identity
        self.action_reset_identity = reset_identity
        self.current_day = current_day
        self.account_id = account_id
        self.server_id = server_id
        self.runtime_scope = runtime_scope
        self.product_id = product_id
        self.product_revision = product_revision
        self.action_executor = action_executor
        self.initial_capture = initial_capture
        self.post_input_delay = post_input_delay
        self.recognition_timeout = recognition_timeout
        self.chest_status = "partial"
        self.challenge_stages: list[dict[str, object]] = []
        self.newly_claimed_chests: list[dict[str, object]] = []
        self.confirmed_claim_records: list[dict[str, object]] = []
        self.challenge_transport_calls = 0
        self.chest_claim_transport_calls = 0
        self.challenge_finished = False
        self.challenge_status = "unknown"
        self.challenge_participation_confirmed = False
        self.daily_action_ready = False
        self.unresolved_action = False
        self._reward_modal_open = False
        self.terminal_home_verified = False
        self.terminal_home_capture = None
        self.atlas_path = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
        self.atlas = load_home_atlas(self.atlas_path)
        self.home_driver = home_driver or BlueStacksLocalizeFirstHomeDriver(
            self.atlas,
            self.atlas_path,
            HomeReadyObservation(True, True, runtime_identity, False, False),
            RUINS_HOME_ATLAS_BUILDING_ID,
            maximum_zoom_inputs=MAXIMUM_HOME_ZOOM_INPUTS,
            maximum_pans=MAXIMUM_HOME_PAN_INPUTS,
        )

        self.zoom_transport = zoom_transport
        self.controller = RuinsRuntimeController(reset_identity=reset_identity)
    def _observe_list(self, label: str):
        captured = self.runtime.capture(label)
        return captured, recognize_ruins_frame(captured.frame, reset_identity=self.reset_identity)

    def _prepare_navigation(self, captured, *, source_state: str, target_roi=None) -> None:
        if not isinstance(self.runtime, NavigationGuardedRuntime):
            raise NavigationBoundaryError("navigation firewall required before transport")
        self.runtime.prepare_source_safety(make_source_safety_facts(
            recognized=True, source_state=source_state, frame_sha256=captured.sha256,
            captured_monotonic=captured.captured_monotonic, target_roi=target_roi,
        ))

    def _ordinary_tap(
        self,
        captured,
        *,
        target_identity: str,
        target_roi,
        action_key: str,
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None:
        """Dispatch a gameplay tap through the bounded native runtime.

        Home entry and safe Back remain behind the navigation firewall.  Ruins
        gameplay controls are ordinary development interactions, so they use
        the underlying runtime's current-frame, bounds, duplicate-input, and
        Cash Mall guards without the navigation-only target allowlist.
        """
        allowed = target_identity in _ORDINARY_RUINS_TARGETS
        if target_identity.startswith("challenge:"):
            allowed = target_identity.split(":", 1)[1] in {
                row_identity for row_identity in self.controller.rows
            } or target_identity.split(":", 1)[1] in {
                "Hero Challenge", "Weapon Trial", "Tech Challenge", "Gear Challenge", "Core Challenge",
                "Nova Challenge", "Module Challenge", "Glory Challenge", "Bioenhancer Challenge",
                "Ultimate Challenge", "Chip Challenge", "Cube Challenge",
            }
        if target_identity.startswith("chest:"):
            allowed = target_identity.split(":", 1)[1] in {
                "Hero Challenge", "Weapon Trial", "Tech Challenge", "Gear Challenge", "Core Challenge",
                "Nova Challenge", "Module Challenge", "Glory Challenge", "Bioenhancer Challenge",
                "Ultimate Challenge", "Chip Challenge", "Cube Challenge",
            }
        if not allowed:
            raise NavigationBoundaryError(f"undeclared Ruins gameplay target denied: {target_identity}")
        inner = getattr(self.runtime, "_inner", None)
        transport = inner if inner is not None else self.runtime
        transport.tap(
            captured,
            target_identity=target_identity,
            target_roi=target_roi,
            action_key=action_key,
            consequential=consequential,
            continuation_of=continuation_of,
        )

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-")

    @classmethod
    def _identity_token(cls, value: str) -> str:
        return f"{cls._slug(value)}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"

    def _action_key(self, category: str) -> str:
        return ruins_daily_action_key(
            flow_id=RUINS_FLOW_ID,
            runtime_scope=self.runtime_scope,
            account_id=self.account_id,
            server_id=self.server_id,
            reset_identity=self.action_reset_identity,
            current_day=self.current_day,
            category=category,
        )

    def _challenge_key(self, row) -> str:
        stage = challenge_stage(row)
        if stage is None:
            raise ValueError("Ruins challenge requires positively read stage progress")
        cleared, maximum = stage
        return self._action_key(f"challenge:{self._slug(row.identity)}:{cleared}:{maximum}")

    def _has_budget(self, inputs: int, *, return_inputs: int = 1) -> bool:
        """Reserve bounded result/return handling as well as the next operation."""

        runtime = getattr(self.runtime, "_inner", self.runtime)
        return bool(
            self.challenge_transport_calls + self.chest_claim_transport_calls < MAX_ACTIONS
            and runtime.input_count + inputs + return_inputs <= min(getattr(runtime, "max_inputs", MAX_INPUTS), MAX_INPUTS)
        )

    def _challenge_preconditions(self, row, detail) -> tuple[str, ...]:
        return (
            f"ruins_product={RUINS_PRODUCT_ID}",
            f"ruins_product_revision={RUINS_PRODUCT_REVISION}",
            f"ruins_flow={RUINS_FLOW_ID}",
            f"ruins_account_id={self._identity_token(self.account_id)}",
            f"ruins_server_id={self._identity_token(self.server_id)}",
            f"ruins_reset_id={self.action_reset_identity}",
            f"ruins_game_day={self.current_day}",
            "ruins_category=challenge",
            f"ruins_challenge_identity={self._slug(row.identity)}",
            f"ruins_challenge_day={row.day_label or 'active_timer'}",
            "ruins_challenge_availability=available",
            "ruins_challenge_control=visible_enabled",
            "ruins_cost_type=none",
            "ruins_cost_amount=0",
            "ruins_premium=false",
            "ruins_paid=false",
            "ruins_ticketed=false",
            "ruins_npc_troops=provided",
            f"ruins_challenge_stage={row.progress_current}/{row.progress_maximum}",
            "ruins_stage_dispatch_count_before=0",
            "ruins_stage_dispatch_count_limit=1",
        )

    def _chest_preconditions(self, row, reward) -> tuple[str, ...]:
        identity = self._slug(row.identity)
        return (
            f"ruins_product={RUINS_PRODUCT_ID}",
            f"ruins_product_revision={RUINS_PRODUCT_REVISION}",
            f"ruins_flow={RUINS_FLOW_ID}",
            f"ruins_account_id={self._identity_token(self.account_id)}",
            f"ruins_server_id={self._identity_token(self.server_id)}",
            f"ruins_reset_id={self.action_reset_identity}",
            f"ruins_game_day={self.current_day}",
            "ruins_category=chest",
            f"ruins_chest_identity={identity}",
            "ruins_chest_state=green_ready",
            "ruins_chest_fully_visible=true",
            "ruins_claim_control=visible_enabled",
            f"ruins_reward_identity={identity}",
            "ruins_cost_type=none",
            "ruins_cost_amount=0",
            "ruins_premium=false",
            "ruins_exchange=false",
            "ruins_shop=false",
            "ruins_claim_count_before=0",
            "ruins_claim_count_limit=1",
        )

    def _policy_observation(
        self,
        captured,
        *,
        source_state: str,
        target_identity: str,
        target_roi,
        control_class: str,
        consequence: str,
        postcondition: str,
    ) -> Observation:
        inner = getattr(self.runtime, "_inner", self.runtime)
        source = identity_from_captured(
            captured,
            session_id=str(inner.session),
            ordinal=inner.ordinal,
            label=f"ruins:{source_state.casefold()}",
        )
        measure_package = getattr(inner, "measure_foreground_package", None)
        package = measure_package() if callable(measure_package) else None
        x0, y0, x1, y1 = target_roi
        crop = captured.frame[y0:y1, x0:x1]
        if crop.size == 0:
            raise ValueError("Ruins action target has an empty current-frame ROI")
        return Observation(
            frame_sha256=captured.sha256,
            capture_completed_monotonic=captured.captured_monotonic,
            runtime_profile_id=source.runtime_profile_id,
            width=source.width,
            height=source.height,
            valid_png=True,
            corrupt=False,
            black=False,
            source_state=source_state,
            overlay_state="none_observed",
            target_identity=target_identity,
            target_roi=tuple(target_roi),
            recognized=True,
            control_class=control_class,
            consequence=consequence,
            cost_type="none",
            cost_amount=0,
            quantity=1,
            expected_postcondition=postcondition,
            evidence_refs=(str(captured.path),),
            critical_roi_hashes=(("ruins-action-target", hashlib.sha256(crop.tobytes()).hexdigest()),),
            ocr_result_frame_sha256=captured.sha256,
            ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            source_family="ruins_challenge",
            target_isolated=True,
            package_foreground=package == "com.global.ztmslg",
        )

    @staticmethod
    def _action_status_value(result) -> str:
        return result.get("status") if isinstance(result, dict) else str(result)


    def _recover_home_zoom_before_ruins_binding(self) -> tuple[CapturedNativeFrame | None, HomeDriverStep | None, str | None]:
        """Return the settled frame and its already-planned step without observing twice."""
        for ordinal in range(1, MAXIMUM_HOME_ZOOM_INPUTS + 1):
            before = self.runtime.capture(f"ruins-home-zoom-{ordinal:02d}-immediate-before")
            step = self.home_driver.observe(before.frame)
            if step.disposition in {
                HomeDriverDisposition.COMPLETE,
                HomeDriverDisposition.BIND,
                HomeDriverDisposition.PAN,
            }:
                return before, step, None
            if step.disposition is HomeDriverDisposition.BLOCKED:
                return None, None, f"home_zoom_recovery_blocked:{step.reason}"
            if step.disposition is not HomeDriverDisposition.RECOVER_ZOOM:
                return None, None, f"home_zoom_recovery_unsupported:{step.disposition.value}"
            try:
                self.runtime.dispatch_zoom_out(
                    before,
                    make_source_safety_facts(
                        recognized=True,
                        source_state="HOME_BASE",
                        frame_sha256=before.sha256,
                        captured_monotonic=before.captured_monotonic,
                    ),
                    transport=(
                        self.zoom_transport.zoom_out_once
                        if self.zoom_transport is not None
                        else None
                    ),
                )
                self.home_driver.record_zoom_input_dispatched(step.source_frame_sha256)
            except NavigationBoundaryError as exc:
                return None, None, str(exc)
            except Exception as exc:
                return None, None, f"android_zoom_transport_failed:{type(exc).__name__}:{exc}"
            self.runtime.capture(f"ruins-home-zoom-{ordinal:02d}-immediate-post")
            if self.post_input_delay > 0:
                time.sleep(self.post_input_delay)
            settled = self.runtime.capture(f"ruins-home-zoom-{ordinal:02d}-settled")
            if settled.sha256 == before.sha256:
                return None, None, "home_zoom_recovery_no_progress"
            post_step = self.home_driver.observe(settled.frame)
            if post_step.disposition is HomeDriverDisposition.BLOCKED:
                return None, None, f"home_zoom_post_reclassification_blocked:{post_step.reason}"
            if post_step.disposition in {
                HomeDriverDisposition.COMPLETE,
                HomeDriverDisposition.BIND,
                HomeDriverDisposition.PAN,
            }:
                return settled, post_step, None
        return None, None, "home_zoom_recovery_exhausted"

    def _pan_home_before_ruins_binding(
        self, captured: CapturedNativeFrame, step: HomeDriverStep,
    ) -> tuple[CapturedNativeFrame | None, str | None]:
        """Execute only calculated Home plans; every input needs measured fresh progress."""
        for ordinal in range(1, MAXIMUM_HOME_PAN_INPUTS + 1):
            if step.disposition in {HomeDriverDisposition.COMPLETE, HomeDriverDisposition.BIND}:
                return captured, None
            if step.disposition is not HomeDriverDisposition.PAN:
                return None, f"home_atlas_pan_blocked:{step.reason}"
            plan = step.plan
            if not isinstance(plan, DirectPanPlan) or plan.drag_start is None or plan.drag_end is None:
                return None, "home_atlas_pan_geometry_unavailable"
            if not is_clean_home_frame(captured.frame):
                return None, "home_atlas_pan_requires_clean_home"
            before_localization = step.localization
            if (
                not before_localization.recognized
                or before_localization.stale
                or before_localization.overlay
            ):
                return None, "home_atlas_pan_source_not_localized"
            action_key = f"ruins:home-pan:{ordinal}:{captured.sha256}"
            self._prepare_navigation(captured, source_state="HOME_BASE")
            self.runtime.swipe(
                captured,
                start=plan.drag_start,
                end=plan.drag_end,
                action_key=action_key,
                target_identity=RUINS_HOME_PAN_TARGET,
            )
            self.runtime.capture(f"ruins-home-pan-{ordinal:02d}-immediate-post")
            if self.post_input_delay > 0:
                time.sleep(self.post_input_delay)
            settled = self.runtime.capture(f"ruins-home-pan-{ordinal:02d}-settled")
            after_localization = self.home_driver.localizer.localize(settled.frame)
            progress = self.home_driver.record_pan_progress(before_localization, after_localization)
            verified = bool(
                settled.sha256 != captured.sha256
                and is_clean_home_frame(settled.frame)
                and progress.accepted
            )
            self.runtime.reconcile(
                action_key, "confirmed" if verified else "unresolved", settled,
                f"home_atlas_pan:{progress.reason}",
            )
            if not verified:
                return None, f"home_atlas_pan_successor_not_verified:{progress.reason}"
            captured = settled
            # Reuse this localization, but obtain a new current-frame plan/binding.
            step = self.home_driver.observe(captured.frame, localization=after_localization)
        if step.disposition in {HomeDriverDisposition.COMPLETE, HomeDriverDisposition.BIND}:
            return captured, None
        return None, "home_atlas_pan_input_limit"


    def _return_home(self, captured, recognition, actions: int) -> IntegratedRouteResult:
        if self._reward_modal_open:
            current = self.runtime.capture("ruins-reward-safe-exit-immediate-before")
            reward = recognize_any_ruins_reward_frame(current.frame, reset_identity=self.reset_identity)
            if reward.recognized and reward.reset_identity == self.reset_identity:
                self._prepare_navigation(current, source_state="RUINS_REWARD_MODAL")
                self.runtime.back(current, action_key=f"ruins:reward-safe-exit:{current.sha256}")
                time.sleep(self.post_input_delay)
                captured, recognition = self._observe_list("ruins-reward-safe-exit-post")
            else:
                captured = current
                recognition = recognize_ruins_frame(current.frame, reset_identity=self.reset_identity)
            if not recognition.observation.recognized or recognition.observation.screen_identity != "RUINS_CHALLENGE":
                return IntegratedRouteResult("blocked", "reward_safe_exit_list_not_recognized", actions, str(self.runtime.session))
            self._reward_modal_open = False
        if is_clean_home_frame(captured.frame) and (
            recognition.observation.home_base_recognized or self._home_atlas_recognized(captured.frame)
        ):
            self.terminal_home_verified = True
            self.terminal_home_capture = captured
            return IntegratedRouteResult("completed", "returned_home", actions, str(self.runtime.session))
        if (
            not recognition.observation.recognized
            or recognition.observation.screen_identity != "RUINS_CHALLENGE"
            or recognition.observation.safe_back_control != RuinsControlState.VISIBLE_ENABLED
        ):
            return IntegratedRouteResult("blocked", "safe_exit_source_not_recognized", actions, str(self.runtime.session))
        immediate_before, rebound = self._observe_list("ruins-safe-exit-immediate-before")
        if (
            not rebound.observation.recognized
            or rebound.observation.screen_identity != "RUINS_CHALLENGE"
            or rebound.observation.safe_back_control != RuinsControlState.VISIBLE_ENABLED
        ):
            return IntegratedRouteResult("blocked", "safe_exit_revalidation_failed", actions, str(self.runtime.session))
        try:
            self._prepare_navigation(immediate_before, source_state="RUINS_CHALLENGE")
        except NavigationBoundaryError as exc:
            return IntegratedRouteResult("blocked", str(exc), actions, str(self.runtime.session))
        self.runtime.back(immediate_before, action_key=f"ruins:safe-exit:{immediate_before.sha256}")
        time.sleep(self.post_input_delay)
        settled, successor = self._observe_list("ruins-safe-exit-immediate-post")
        if not is_clean_home_frame(settled.frame) or (
            not successor.observation.home_base_recognized and not self._home_atlas_recognized(settled.frame)
        ):
            return IntegratedRouteResult("blocked", "safe_exit_home_successor_not_recognized", actions, str(self.runtime.session))
        self.terminal_home_verified = True
        self.terminal_home_capture = settled
        return IntegratedRouteResult("completed", "verified_safe_exit_to_home", actions, str(self.runtime.session))

    def _home_atlas_recognized(self, frame) -> bool:
        return bool(BlueStacksHomeLocalizer(self.atlas, self.atlas_path).localize(frame).recognized)


    def _current_frame_ruins_binding(self, captured: CapturedNativeFrame) -> tuple[int, int, int, int] | None:
        localization = self.home_driver.localizer.localize(captured.frame)
        if not localization.recognized or localization.stale or localization.overlay:
            return None
        building = self.atlas.lookup_building(RUINS_HOME_ATLAS_BUILDING_ID)
        binding = bind_visible_building(
            captured.frame, localization, building, home_is_clean=is_clean_home_frame,
        )
        if (
            binding is None
            or binding.building_id != RUINS_HOME_ATLAS_BUILDING_ID
            or binding.frame_sha256 != localization.frame_sha256
            or binding.atlas_anchor != building.interaction_anchor
            or not binding.semantic_evidence
            or binding.confidence < 0.80
            or binding.overlay_intersects
            or binding.ambiguous_overlap
        ):
            return None
        left, top, right, bottom = binding.target_roi
        return left, top, right, bottom

    def _claim_one_chest(self, captured, recognition):
        observation = recognition.observation
        for row in observation.rows:
            if row.chest_state != RuinsChestState.AVAILABLE or not self._fully_visible_chest_row(row):
                continue
            target_identity = f"chest:{row.identity}"
            target = recognition.target(target_identity)
            action_key = self._action_key(f"chest:{self._slug(row.identity)}")
            if target is None:
                return "blocked", "green_ready_chest_claim_not_authorized", captured, recognition
            spec = {
                "action_key": action_key,
                "semantic_action": RUINS_CHEST_CLAIM_ACTION,
                "action_kind": RUINS_CHEST_CLAIM_ACTION,
                "subject": f"ruins_stage_chest:{self._slug(row.identity)}",
                "category": "chest",
                "identity": row.identity,
                "source_state": "RUINS_REWARD_MODAL",
                "target_identity": "ruins-reward-claim",
                "control_class": "CLAIM",
                "consequence": "ruins_zero_cost_ready_chest_reward",
                "expected_postcondition": RUINS_CHEST_CLAIM_POSTCONDITION,
                "semantic_preconditions": (),
                "game_day_id": self.action_reset_identity,
            }
            existing = self.action_executor.status(spec)
            existing_status = self._action_status_value(existing)
            if existing_status == "confirmed":
                return "blocked", "confirmed_chest_still_green_ready_no_retry", captured, recognition
            if existing_status != "new":
                if existing_status in {"unknown", "unresolved"}:
                    self.unresolved_action = True
                return "unresolved" if existing_status in {"unknown", "unresolved"} else "blocked", (
                    f"canonical_chest_action_{existing_status}"
                ), captured, recognition
            planned = self.controller.plan_chest_claim(
                observation, row, action_key=action_key,
            )
            if planned.kind != "claim_chest":
                return "blocked", planned.reason, captured, recognition
            self._ordinary_tap(
                captured,
                target_identity=target_identity,
                target_roi=target,
                action_key=f"{action_key}:open:{captured.sha256}",
                consequential=False,
            )
            self._reward_modal_open = True
            time.sleep(self.post_input_delay)
            modal_capture = self.runtime.capture("chest-modal-immediate-post")
            modal = recognize_ruins_reward_frame(
                modal_capture.frame, row.identity, reset_identity=self.reset_identity,
            )
            claim_target = modal.target("ruins-reward-claim")
            if (
                not modal.recognized
                or modal.identity != row.identity
                or modal.reset_identity != self.reset_identity
                or claim_target is None
            ):
                return "blocked", "ruins_reward_modal_not_exact_zero_cost_identity", modal_capture, recognition
            spec["semantic_preconditions"] = self._chest_preconditions(row, modal)
            proposal = self._policy_observation(
                modal_capture,
                source_state="RUINS_REWARD_MODAL",
                target_identity="ruins-reward-claim",
                target_roi=claim_target,
                control_class="CLAIM",
                consequence="ruins_zero_cost_ready_chest_reward",
                postcondition=RUINS_CHEST_CLAIM_POSTCONDITION,
            )
            facts: dict[str, object] = {"captures": []}

            def observe(current):
                recognized = recognize_ruins_reward_frame(
                    current.frame, row.identity, reset_identity=self.reset_identity,
                )
                current_target = recognized.target("ruins-reward-claim")
                if (
                    not recognized.recognized
                    or recognized.identity != row.identity
                    or recognized.reset_identity != self.reset_identity
                    or current_target is None
                ):
                    return None
                facts["modal"] = recognized
                return self._policy_observation(
                    current,
                    source_state="RUINS_REWARD_MODAL",
                    target_identity="ruins-reward-claim",
                    target_roi=current_target,
                    control_class="CLAIM",
                    consequence="ruins_zero_cost_ready_chest_reward",
                    postcondition=RUINS_CHEST_CLAIM_POSTCONDITION,
                )

            def dispatch(current, current_observation):
                if (
                    current_observation.frame_sha256 != current.sha256
                    or current_observation.target_identity != "ruins-reward-claim"
                    or current_observation.expected_postcondition != RUINS_CHEST_CLAIM_POSTCONDITION
                ):
                    raise NavigationBoundaryError("Ruins Claim target changed before canonical dispatch")
                self.controller.mark_input_sent(action_key)
                self._ordinary_tap(
                    current,
                    target_identity="ruins-reward-claim",
                    target_roi=current_observation.target_roi,
                    action_key=action_key,
                    consequential=True,
                )

            def successor(after):
                post_capture, post_recognition = (
                    after,
                    recognize_ruins_frame(after.frame, reset_identity=self.reset_identity),
                )
                next_observation = post_recognition.observation
                next_row = next_observation.row(row.identity)
                if next_observation.recognized and next_observation.screen_identity == "RUINS_CHALLENGE":
                    self._reward_modal_open = False
                proven = bool(
                    next_observation.recognized
                    and next_observation.screen_identity == "RUINS_CHALLENGE"
                    and next_observation.reset_identity == self.reset_identity
                    and next_observation.source_frame_sha256 != row.source_frame_sha256
                    and post_recognition.target(target_identity) is None
                    # The exact green-ready target becomes spent in this same
                    # fully visible, identified row. Wallet/reward OCR is not authority.
                    and next_row is not None
                    and next_row.recognized
                    and self._fully_visible_chest_row(next_row)
                    and next_row.reset_identity == row.reset_identity
                    and next_row.chest_state in {RuinsChestState.UNKNOWN, RuinsChestState.CLAIMED}
                )
                facts["captures"].append((post_capture, post_recognition, proven))
                return RUINS_CHEST_CLAIM_POSTCONDITION if proven else "unknown"

            result = self.action_executor.execute(
                spec=spec,
                proposal_capture=modal_capture,
                proposal_observation=proposal,
                capture=lambda label: self.runtime.capture(label),
                observe=observe,
                dispatch=dispatch,
                successor=successor,
                settle_seconds=self.post_input_delay,
            )
            status = self._action_status_value(result)
            transport_calls = result.get("transport_calls", 0) if isinstance(result, dict) else 0
            if type(transport_calls) is int and transport_calls >= 0:
                self.chest_claim_transport_calls += transport_calls
            captures = facts["captures"]
            if status != "confirmed" or not captures or not captures[-1][2]:
                self.unresolved_action = status in {"unknown", "unresolved"}
                if not self.unresolved_action and transport_calls == 0:
                    self.controller.release_unsent(action_key)
                if captures:
                    post_capture, post_recognition = captures[-1][0], captures[-1][1]
                else:
                    post_capture, post_recognition = modal_capture, recognition
                return (
                    "unresolved" if self.unresolved_action else "blocked",
                    str(result.get("reason", "canonical_chest_claim_not_confirmed")),
                    post_capture,
                    post_recognition,
                )
            post_capture, post_recognition, _proven = captures[-1]
            after = replace(
                post_recognition.observation.row(row.identity),
                chest_state=RuinsChestState.CLAIMED,
            )
            reconciled = self.controller.reconcile_chest(row, after, action_key=action_key)
            if reconciled.kind != "chest_reconciled":
                self.unresolved_action = True
                return "unresolved", reconciled.reason, post_capture, post_recognition
            self.newly_claimed_chests.append({"identity": row.identity})
            self.confirmed_claim_records.append(make_claim_record(
                identity=row.identity,
                action_key=action_key,
                source_frame_path=captured.path,
                source_frame_sha256=captured.sha256,
                post_frame_path=post_capture.path,
                post_frame_sha256=post_capture.sha256,
                reset_identity=self.reset_identity,
            ))
            return "claimed", row.identity, post_capture, post_recognition
        return "none", "no_available_chest", captured, recognition

    @staticmethod
    def _fully_visible_chest_row(row) -> bool:
        roi = row.target_roi
        return roi is not None and roi[1] >= 210 and roi[3] - roi[1] >= 190


    @staticmethod
    def _visible_row_signature(recognition) -> dict[str, tuple[int, int]]:
        return {
            row.identity: (row.target_roi[1], row.target_roi[3])
            for row in recognition.observation.rows
            if row.target_roi is not None
        }

    def _scroll_chest_list(self, captured, recognition, *, ordinal: int):
        if not recognition.observation.recognized or recognition.observation.screen_identity != "RUINS_CHALLENGE":
            return "blocked", "ruins_list_scroll_source_not_recognized", captured, recognition
        signature = self._visible_row_signature(recognition)
        if not signature:
            return "blocked", "ruins_list_scroll_has_no_bound_rows", captured, recognition
        row_bottom = max(bottom for _top, bottom in signature.values())
        start_y = min(1100, max(900, row_bottom - 30))
        end_y = max(330, start_y - 700)
        start = (400, start_y)
        end = (400, end_y)
        swipe_roi = (390, end_y, 411, start_y + 1)
        try:
            self._prepare_navigation(captured, source_state="RUINS_CHALLENGE", target_roi=swipe_roi)
            self.runtime.swipe(
                captured,
                start=start,
                end=end,
                action_key=f"ruins:chest-scroll:{self.reset_identity}:{ordinal}:{captured.sha256}",
                target_identity=RUINS_LIST_SCROLL_TARGET,
            )
        except NavigationBoundaryError as exc:
            return "blocked", str(exc), captured, recognition
        time.sleep(self.post_input_delay)
        post_capture, post_recognition = self._observe_list(f"chest-coverage-scroll-{ordinal:02d}-immediate-post")
        if not post_recognition.observation.recognized or post_recognition.observation.screen_identity != "RUINS_CHALLENGE":
            return "blocked", "ruins_list_scroll_postcondition_not_recognized", post_capture, post_recognition
        post_signature = self._visible_row_signature(post_recognition)
        ready_after = any(
            row.chest_state == RuinsChestState.AVAILABLE and self._fully_visible_chest_row(row)
            for row in post_recognition.observation.rows
        )
        if post_signature == signature and not ready_after:
            return "end", "ruins_list_end_observed", post_capture, post_recognition
        return "scrolled", "ruins_list_scroll_progress", post_capture, post_recognition



    def _choose_challenge(self, recognition):
        action_key = "stage-recognition"
        for row in recognition.observation.rows:
            if (
                challenge_action_authorized(
                    recognition.observation,
                    row,
                    current_day=self.current_day,
                    action_key=action_key,
                )
                and recognition.target(f"challenge:{row.identity}") is not None
            ):
                return row
        return None

    def _safe_back_unavailable_detail(self, identity: str):
        immediate = self.runtime.capture("challenge-unavailable-safe-back-immediate-before")
        detail = recognize_ruins_detail_with_targets(
            immediate.frame, identity, reset_identity=self.reset_identity,
        ).observation
        if not detail.recognized or detail.overlay_state != "none":
            return None
        source_state = (
            "RUINS_DISPATCH_DETAIL"
            if detail.dispatch_control == RuinsControlState.VISIBLE_ENABLED
            else "RUINS_CHALLENGE_DETAIL"
        )
        try:
            self._prepare_navigation(immediate, source_state=source_state)
            self.runtime.back(
                immediate,
                action_key=f"ruins:challenge-unavailable-safe-back:{immediate.sha256}",
            )
        except NavigationBoundaryError:
            return None
        time.sleep(self.post_input_delay)
        captured, recognition = self._observe_list("challenge-unavailable-list-immediate-post")
        if (
            not recognition.observation.recognized
            or recognition.observation.screen_identity != "RUINS_CHALLENGE"
            or recognition.observation.reset_identity != self.reset_identity
        ):
            return None
        return captured, recognition

    def _safe_exit_after_challenge_problem(self, reason: str, *, unresolved: bool) -> IntegratedRouteResult:
        """Use only a currently recognized Ruins successor to leave an unresolved challenge."""

        current = self.runtime.capture("ruins-challenge-problem-safe-exit-source")
        dispatch_count = self.challenge_transport_calls + self.chest_claim_transport_calls
        if is_clean_home_frame(current.frame):
            self.terminal_home_verified = True
            self.terminal_home_capture = current
            return IntegratedRouteResult(
                "unresolved" if unresolved else "blocked",
                f"{reason};verified_safe_exit_to_home",
                dispatch_count,
                str(self.runtime.session),
            )
        list_recognition = recognize_ruins_frame(current.frame, reset_identity=self.reset_identity)
        if (
            list_recognition.observation.recognized
            and list_recognition.observation.screen_identity == "RUINS_CHALLENGE"
            and list_recognition.observation.reset_identity == self.reset_identity
        ):
            home = self._return_home(current, list_recognition, dispatch_count)
            if home.status == "completed":
                return IntegratedRouteResult(
                    "unresolved" if unresolved else "blocked",
                    f"{reason};verified_safe_exit_to_home",
                    dispatch_count,
                    str(self.runtime.session),
                )
            return IntegratedRouteResult(
                "unresolved" if unresolved else "blocked",
                f"{reason};{home.reason}",
                dispatch_count,
                str(self.runtime.session),
            )
        for identity in KNOWN_CHALLENGE_IDENTITIES:
            result = recognize_ruins_result_with_targets(
                current.frame,
                identity,
                reset_identity=self.reset_identity,
            )
            result_observation = result.observation
            continue_target = result.target("ruins-result-continue")
            if (
                result_observation.identity == identity
                and result_observation.reset_identity == self.reset_identity
                and result_observation.tap_to_continue_visible
                and continue_target is not None
            ):
                try:
                    self._ordinary_tap(
                        current,
                        target_identity="ruins-result-continue",
                        target_roi=continue_target,
                        action_key=f"ruins:challenge-problem-continue:{current.sha256}",
                    )
                except NavigationBoundaryError:
                    break
                time.sleep(self.post_input_delay)
                listed, recognition = self._observe_list("ruins-challenge-problem-list-post")
                if (
                    recognition.observation.recognized
                    and recognition.observation.screen_identity == "RUINS_CHALLENGE"
                    and recognition.observation.reset_identity == self.reset_identity
                ):
                    home = self._return_home(listed, recognition, dispatch_count)
                    if home.status == "completed":
                        return IntegratedRouteResult(
                            "unresolved" if unresolved else "blocked",
                            f"{reason};verified_safe_exit_to_home",
                            dispatch_count,
                            str(self.runtime.session),
                        )
                break
        for identity in KNOWN_CHALLENGE_IDENTITIES:
            detail = recognize_ruins_detail_with_targets(
                current.frame,
                identity,
                reset_identity=self.reset_identity,
            ).observation
            if not detail.recognized or detail.reset_identity != self.reset_identity or detail.overlay_state != "none":
                continue
            source_state = (
                "RUINS_DISPATCH_DETAIL"
                if detail.dispatch_control == RuinsControlState.VISIBLE_ENABLED
                else "RUINS_CHALLENGE_DETAIL"
            )
            try:
                self._prepare_navigation(current, source_state=source_state)
                self.runtime.back(
                    current,
                    action_key=f"ruins:challenge-problem-safe-back:{identity}:{current.sha256}",
                )
            except NavigationBoundaryError:
                break
            time.sleep(self.post_input_delay)
            listed, recognition = self._observe_list("ruins-challenge-problem-detail-exit-post")
            if (
                recognition.observation.recognized
                and recognition.observation.screen_identity == "RUINS_CHALLENGE"
                and recognition.observation.reset_identity == self.reset_identity
            ):
                home = self._return_home(listed, recognition, dispatch_count)
                if home.status == "completed":
                    return IntegratedRouteResult(
                        "unresolved" if unresolved else "blocked",
                        f"{reason};verified_safe_exit_to_home",
                        dispatch_count,
                        str(self.runtime.session),
                    )
            break
        return IntegratedRouteResult(
            "unresolved" if unresolved else "blocked",
            f"{reason};safe_exit_not_proven",
            dispatch_count,
            str(self.runtime.session),
        )

    def _run_challenge(self, captured, recognition, row):
        action_key = self._challenge_key(row)
        planned = self.controller.plan_challenge(
            recognition.observation,
            row,
            current_day=self.current_day,
            action_key=action_key,
        )
        if planned.kind != "open_detail":
            return IntegratedRouteResult("blocked", planned.reason, 0, str(self.runtime.session))
        target = recognition.target(f"challenge:{row.identity}")
        if target is None:
            return IntegratedRouteResult("blocked", "challenge_row_target_not_bound", 0, str(self.runtime.session))
        self._ordinary_tap(
            captured,
            target_identity=f"challenge:{row.identity}",
            target_roi=target,
            action_key=f"{action_key}:open:{captured.sha256}",
        )
        time.sleep(self.post_input_delay)
        detail_capture = self.runtime.capture("challenge-detail-immediate-post")
        detail = recognize_ruins_detail_with_targets(
            detail_capture.frame,
            row.identity,
            reset_identity=self.reset_identity,
        )
        attack_target = detail.target("ruins-attack")
        attack = self.controller.plan_attack(detail.observation, action_key=action_key)
        if attack.kind != "attack" or attack_target is None:
            recovered = self._safe_back_unavailable_detail(row.identity)
            if recovered is not None:
                self.controller.release_unsent(action_key)
                return recovered[0], recovered[1], None
            return IntegratedRouteResult("blocked", "detail or zero-cost Attack control not positively recognized", 0, str(self.runtime.session))
        self._ordinary_tap(
            detail_capture,
            target_identity="ruins-attack",
            target_roi=attack_target,
            action_key=f"{action_key}:attack",
        )
        time.sleep(self.post_input_delay)
        dispatch_capture = self.runtime.capture("dispatch-control-immediate-before")
        dispatch_recognition = recognize_ruins_detail_with_targets(
            dispatch_capture.frame,
            row.identity,
            reset_identity=self.reset_identity,
        )
        dispatch_observation = replace(
            dispatch_recognition.observation,
            floor_current=detail.observation.floor_current,
            floor_maximum=detail.observation.floor_maximum,
            attack_control=detail.observation.attack_control,
        )
        dispatch_target = dispatch_recognition.target("ruins-dispatch")
        if not dispatch_authorized(dispatch_observation) or dispatch_target is None:
            recovered = self._safe_back_unavailable_detail(row.identity)
            if recovered is not None:
                self.controller.release_unsent(action_key)
                return recovered[0], recovered[1], None
            return IntegratedRouteResult("blocked", "zero-cost NPC Dispatch contract not proven", 0, str(self.runtime.session))
        action_spec = {
            "action_key": action_key,
            "semantic_action": RUINS_CHALLENGE_DISPATCH_ACTION,
            "action_kind": RUINS_CHALLENGE_DISPATCH_ACTION,
            "subject": f"ruins_challenge:{self._slug(row.identity)}",
            "category": "challenge",
            "identity": row.identity,
            "source_state": "RUINS_CHALLENGE_DETAIL",
            "target_identity": "ruins-dispatch",
            "control_class": "DISPATCH",
            "consequence": "ruins_zero_cost_npc_challenge",
            "expected_postcondition": RUINS_CHALLENGE_RESULT_POSTCONDITION,
            "semantic_preconditions": self._challenge_preconditions(row, dispatch_observation),
            "game_day_id": self.action_reset_identity,
        }
        existing = self.action_executor.status(action_spec)
        existing_status = self._action_status_value(existing)
        if existing_status != "new":
            return IntegratedRouteResult(
                "unresolved" if existing_status in {"unknown", "unresolved"} else "blocked",
                f"canonical_challenge_action_{existing_status}",
                0,
                str(self.runtime.session),
            )
        proposal = self._policy_observation(
            dispatch_capture,
            source_state="RUINS_CHALLENGE_DETAIL",
            target_identity="ruins-dispatch",
            target_roi=dispatch_target,
            control_class="DISPATCH",
            consequence="ruins_zero_cost_npc_challenge",
            postcondition=RUINS_CHALLENGE_RESULT_POSTCONDITION,
        )
        facts: dict[str, object] = {"results": []}

        def observe(current):
            current_recognition = recognize_ruins_detail_with_targets(
                current.frame, row.identity, reset_identity=self.reset_identity,
            )
            current_detail = replace(
                current_recognition.observation,
                floor_current=detail.observation.floor_current,
                floor_maximum=detail.observation.floor_maximum,
                attack_control=detail.observation.attack_control,
            )
            current_target = current_recognition.target("ruins-dispatch")
            if not dispatch_authorized(current_detail) or current_target is None:
                return None
            facts["dispatch"] = (current, current_recognition, current_detail)
            return self._policy_observation(
                current,
                source_state="RUINS_CHALLENGE_DETAIL",
                target_identity="ruins-dispatch",
                target_roi=current_target,
                control_class="DISPATCH",
                consequence="ruins_zero_cost_npc_challenge",
                postcondition=RUINS_CHALLENGE_RESULT_POSTCONDITION,
            )

        def dispatch(current, current_observation):
            if (
                current_observation.frame_sha256 != current.sha256
                or current_observation.target_identity != "ruins-dispatch"
                or current_observation.expected_postcondition != RUINS_CHALLENGE_RESULT_POSTCONDITION
            ):
                raise NavigationBoundaryError("Ruins Dispatch target changed before canonical dispatch")
            self.controller.mark_input_sent(action_key)
            self._ordinary_tap(
                current,
                target_identity="ruins-dispatch",
                target_roi=current_observation.target_roi,
                action_key=action_key,
                consequential=True,
            )

        def successor(after):
            result_recognition = recognize_ruins_result_with_targets(
                after.frame,
                row.identity,
                before_progress=row.progress_current,
                reset_identity=self.reset_identity,
            )
            valid = bool(
                result_verified(row, result_recognition.observation)
                and result_recognition.target("ruins-result-continue") is not None
            )
            facts["results"].append((after, result_recognition, valid))
            if valid:
                action_spec["result"] = result_recognition.observation.result.value
            return RUINS_CHALLENGE_RESULT_POSTCONDITION if valid else "unknown"

        result = self.action_executor.execute(
            spec=action_spec,
            proposal_capture=dispatch_capture,
            proposal_observation=proposal,
            capture=lambda label: self.runtime.capture(label),
            observe=observe,
            dispatch=dispatch,
            successor=successor,
            settle_seconds=self.post_input_delay,
        )
        status = self._action_status_value(result)
        transport_calls = result.get("transport_calls", 0) if isinstance(result, dict) else 0
        if type(transport_calls) is int and transport_calls >= 0:
            self.challenge_transport_calls += transport_calls
        if status != "confirmed" or not facts["results"] or not facts["results"][-1][2]:
            self.unresolved_action = status in {"unknown", "unresolved"}
            if not self.unresolved_action and transport_calls == 0:
                self.controller.release_unsent(action_key)
            reason = result.get("reason", "challenge_participation_not_confirmed") if isinstance(result, dict) else "challenge_participation_not_confirmed"
            return IntegratedRouteResult(
                "unresolved" if self.unresolved_action else "blocked",
                str(reason),
                0,
                str(self.runtime.session),
            )
        result_capture, result_recognition, _valid = facts["results"][-1]
        self.challenge_stages.append({
            "identity": row.identity,
            "stage_cleared": row.progress_current,
            "stage_maximum": row.progress_maximum,
            "result": result_recognition.observation.result.value,
        })
        self.challenge_participation_confirmed = True
        self.daily_action_ready = True
        self._ordinary_tap(
            result_capture,
            target_identity="ruins-result-continue",
            target_roi=result_recognition.target("ruins-result-continue"),
            action_key=f"{action_key}:continue",
            continuation_of=action_key,
        )
        time.sleep(self.post_input_delay)
        list_capture, list_recognition = self._observe_list("challenge-list-postcondition")
        if (
            not list_recognition.observation.recognized
            or list_recognition.observation.screen_identity != "RUINS_CHALLENGE"
            or list_recognition.observation.reset_identity != self.reset_identity
        ):
            return IntegratedRouteResult("unresolved", "challenge_list_postcondition_not_recognized", 0, str(self.runtime.session))
        result_observation = result_recognition.observation
        reconciled = self.controller.reconcile_result(row, result_observation)
        if reconciled.kind != "reconciled":
            return IntegratedRouteResult("unresolved", reconciled.reason, 0, str(self.runtime.session))
        return list_capture, list_recognition, result_observation.result

    def _enter_ruins(self) -> IntegratedRouteResult | tuple[CapturedNativeFrame, RuinsFrameRecognition]:
        """Reach a positively recognized Ruins-owned list before gameplay is considered."""
        if not self.runtime.execute:
            return IntegratedRouteResult(
                "blocked",
                "ruins_consequential_route_requires_canonical_native_executor",
                0,
                str(self.runtime.session),
            )
        captured = self.initial_capture or self.runtime.capture("ruins-canonical-home-source")
        if not is_clean_home_frame(captured.frame):
            return IntegratedRouteResult("blocked", "canonical_clean_home_required", 0, str(self.runtime.session))
        # The driver records each proposed zoom source. Let one owner observe and
        # consume that plan; observing this same frame twice rejects it as a retry.
        captured, preparation, preparation_error = self._recover_home_zoom_before_ruins_binding()
        if (
            preparation_error is not None
            or captured is None
            or preparation is None
            or not is_clean_home_frame(captured.frame)
        ):
            return IntegratedRouteResult(
                "blocked",
                preparation_error or "home_zoom_did_not_restore_clean_home",
                0,
                str(self.runtime.session),
            )
        if preparation.disposition is HomeDriverDisposition.PAN:
            captured, preparation_error = self._pan_home_before_ruins_binding(captured, preparation)
            if preparation_error is not None or captured is None:
                return IntegratedRouteResult(
                    "blocked", preparation_error or "home_atlas_pan_failed", 0, str(self.runtime.session),
                )
        target = self._current_frame_ruins_binding(captured)
        if target is None:
            return IntegratedRouteResult("blocked", "home_atlas_ruins_not_bound", 0, str(self.runtime.session))
        try:
            self._prepare_navigation(captured, source_state="HOME_BASE", target_roi=target)
            self.runtime.tap(
                captured,
                target_identity=RUINS_HOME_ATLAS_BUILDING_ID,
                target_roi=target,
                action_key=f"ruins:open:{captured.sha256}",
            )
        except NavigationBoundaryError as exc:
            return IntegratedRouteResult("blocked", str(exc), 0, str(self.runtime.session))
        time.sleep(self.post_input_delay)
        captured, recognition = self._observe_list("ruins-list-immediate-post")
        if (
            not recognition.observation.recognized
            or recognition.observation.screen_identity != "RUINS_CHALLENGE"
            or recognition.observation.reset_identity != self.reset_identity
        ):
            return IntegratedRouteResult("blocked", "Ruins list not positively recognized", 0, str(self.runtime.session))
        return captured, recognition

    def run(self, *, max_steps: int = 30) -> IntegratedRouteResult:
        entry = self._enter_ruins()
        if isinstance(entry, IntegratedRouteResult):
            return entry
        captured, recognition = entry
        self.controller.observe_list(recognition.observation)

        progress = self.action_executor.reset_progress(self._action_key("challenge"))
        self.controller.restore_reset_progress(
            stages_confirmed=progress["stages_confirmed"],
            stages_won=progress["stages_won"],
            finished=progress["finished"],
        )
        self.challenge_participation_confirmed = self.controller.daily.participation_confirmed
        self.daily_action_ready = self.challenge_participation_confirmed
        if progress["unresolved"]:
            self.unresolved_action = True
            self.challenge_status = "unresolved"
            return self._safe_exit_after_challenge_problem("canonical_unresolved_action_no_retry", unresolved=True)

        partial_reason = None
        self.challenge_finished = progress["finished"]
        self.challenge_status = "finished" if self.challenge_finished else "unknown"
        for _ in range(max_steps):
            if self.challenge_finished:
                break
            row = self._choose_challenge(recognition)
            if row is None:
                applicable = [
                    candidate for candidate in recognition.observation.rows
                    if candidate.day_label is None or candidate.day_label == self.current_day
                ]
                if applicable and all(
                    candidate.recognized
                    and candidate.availability in {
                        RuinsAvailability.LOCKED, RuinsAvailability.UNAVAILABLE,
                        RuinsAvailability.EXPIRED, RuinsAvailability.PREMIUM,
                    }
                    and candidate.challenge_control != RuinsControlState.VISIBLE_ENABLED
                    for candidate in applicable
                ):
                    self.challenge_status = "unavailable"
                else:
                    partial_reason = "challenge_stage_not_positively_identified"
                break
            # Reserve the currently observed independent green-ready batch,
            # bounded overview scanning, and modal/Home return handling.
            # These are visit limits, never a reset participation cap.
            ready_count = len({
                candidate.identity for candidate in recognition.observation.rows
                if candidate.chest_state == RuinsChestState.AVAILABLE
                and self._fully_visible_chest_row(candidate)
            })
            chest_reserve = 2 * ready_count + MAXIMUM_RUINS_CHEST_SCROLLS + 2
            calls = self.challenge_transport_calls + self.chest_claim_transport_calls
            if not self._has_budget(4, return_inputs=chest_reserve) or calls + 1 + ready_count > MAX_ACTIONS:
                self.challenge_status = "paused"
                partial_reason = "challenge_visit_budget_paused"
                break
            challenge_result = self._run_challenge(captured, recognition, row)
            if isinstance(challenge_result, IntegratedRouteResult):
                if self.unresolved_action or challenge_result.status == "unresolved":
                    self.challenge_status = "unresolved"
                    return self._safe_exit_after_challenge_problem(challenge_result.reason, unresolved=True)
                # Only never-sent planning state may be released. A canonical
                # UNKNOWN never reaches this branch or grants chest permission.
                self.controller.release_unsent(self._challenge_key(row))
                recovered = self._safe_back_unavailable_detail(row.identity)
                if recovered is None:
                    current, current_recognition = self._observe_list("challenge-unsent-list-recheck")
                    if not current_recognition.observation.recognized:
                        return self._safe_exit_after_challenge_problem(challenge_result.reason, unresolved=False)
                    recovered = current, current_recognition
                captured, recognition = recovered
                self.challenge_status = "unknown"
                partial_reason = challenge_result.reason
                break
            captured, recognition, result = challenge_result
            self.controller.observe_list(recognition.observation)
            if result is None:
                self.challenge_status = "unavailable"
                break
            self.challenge_participation_confirmed = True
            self.daily_action_ready = True
            if result == RuinsResult.FAILURE:
                self.challenge_finished = True
                self.challenge_status = "finished"
                break
        else:
            self.challenge_status = "paused"
            partial_reason = "challenge_visit_step_limit_paused"

        scroll_ordinal = 0
        for _ in range(max_steps):
            ready = any(
                row.chest_state == RuinsChestState.AVAILABLE and self._fully_visible_chest_row(row)
                for row in recognition.observation.rows
            )
            if ready:
                if not self._has_budget(2, return_inputs=2):
                    partial_reason = partial_reason or "chest_visit_budget_paused"
                    break
                chest_status, reason, captured, recognition = self._claim_one_chest(captured, recognition)
                if chest_status == "claimed":
                    self.controller.observe_list(recognition.observation)
                    continue
                partial_reason = reason
                self.unresolved_action = self.unresolved_action or chest_status == "unresolved"
                if self.unresolved_action:
                    self.chest_status = "unresolved"
                break
            if scroll_ordinal >= MAXIMUM_RUINS_CHEST_SCROLLS or not self._has_budget(1):
                partial_reason = partial_reason or "chest_visit_scan_budget_paused"
                break
            scroll_ordinal += 1
            scroll_status, scroll_reason, captured, recognition = self._scroll_chest_list(
                captured, recognition, ordinal=scroll_ordinal,
            )
            if scroll_status == "end":
                self.chest_status = "complete"
                break
            if scroll_status != "scrolled":
                partial_reason = scroll_reason
                break
            self.controller.observe_list(recognition.observation)
        else:
            partial_reason = partial_reason or "chest_visit_step_limit_paused"

        dispatch_count = self.challenge_transport_calls + self.chest_claim_transport_calls
        home = self._return_home(captured, recognition, dispatch_count)
        if home.status != "completed":
            return home
        if partial_reason is not None:
            return IntegratedRouteResult(
                "unresolved",
                f"{partial_reason};verified_safe_exit_to_home",
                dispatch_count,
                str(self.runtime.session),
            )
        return IntegratedRouteResult(
            "completed",
            "verified_safe_exit_to_home",
            dispatch_count,
            str(self.runtime.session),
        )


def _retained_dispatch_count(events_path) -> int:
    """Count unique transport dispatch rows retained by one native runtime session."""

    action_keys: set[str] = set()
    for line in Path(events_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("type") != "dispatch":
            continue
        action_key = row.get("action_key")
        if not isinstance(action_key, str) or not action_key or action_key in action_keys:
            raise ValueError("Ruins retained dispatch journal has a missing or duplicate action key")
        action_keys.add(action_key)
    return len(action_keys)


def adopt_ruins_route_transports(context) -> int:
    """Bind the Ruins runtime's journal-proven transports to the borrowed session.

    Ruins dispatches Home zoom, navigation and canonical-executor inputs through
    the native runtime rather than ``DevelopmentSession.run_action``.  The
    session owns those inputs by adopting the runtime's cumulative count from
    the same retained journal used for startup recovery, and only after that
    count is proven equal to the journal's unique dispatch rows.
    """

    runtime_count = context.runtime.input_count
    retained_count = _retained_dispatch_count(context.runtime.events)
    if type(runtime_count) is not int or runtime_count != retained_count:
        raise ValueError("Ruins runtime input count differs from its retained dispatch journal")
    return context.session.adopt_retained_transport_count(
        runtime_count, source=str(context.runtime.events)
    )


def execute_ruins_route(context, arguments):
    """Fixed service driver for one canonical Home-to-Ruins visit."""

    from datetime import datetime, timezone

    identity = context.identity
    required_arguments = {
        "account_id",
        "action_executor_factory",
        "current_day",
        "runtime_identity",
        "runtime_scope",
        "server_id",
    }
    if set(arguments) != required_arguments:
        raise ValueError("Ruins native route arguments do not match the fixed route contract")
    if (
        context.flow_id != RUINS_FLOW_ID
        or context.product_id != RUINS_PRODUCT_ID
        or context.product_revision != RUINS_PRODUCT_REVISION
        or context.runtime_profile_id != RUINS_PROFILE_ID
        or getattr(identity, "task_id", None) != RUINS_PRODUCT_ID
    ):
        raise ValueError("Ruins native route identity mismatch")
    current_day = arguments["current_day"]
    account_id = arguments["account_id"]
    server_id = arguments["server_id"]
    runtime_identity = arguments["runtime_identity"]
    runtime_scope = arguments["runtime_scope"]
    action_executor_factory = arguments["action_executor_factory"]
    if (
        not isinstance(current_day, str)
        or current_day not in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
        or account_id != identity.account_id
        or server_id != identity.server_id
        or not isinstance(runtime_identity, VerifiedRuntimeIdentity)
        or runtime_identity.runtime_scope != runtime_scope
        or not callable(action_executor_factory)
    ):
        raise ValueError("Ruins native route has an invalid current identity binding")
    context.validate_identity()
    initial = context.initial_frame
    if not context.is_clean_home(initial.frame):
        startup = context.prepare_startup(
            source_context=RUINS_FLOW_ID,
            recognize_successor=lambda captured: context.is_clean_home(captured.frame),
            action_key=f"ruins-startup:{identity.reset_id}",
            settle_seconds=context.settle_seconds,
        )
        if (
            not startup.resume_ready
            or startup.settled_frame is None
            or not context.is_clean_home(startup.settled_frame.frame)
        ):
            raise ValueError("Ruins startup recovery did not reach canonical clean Home")
        initial = startup.settled_frame
    else:
        context.bind_initial_observation(
            initial,
            extra={
                "ruins_flow_id": RUINS_FLOW_ID,
                "ruins_product_id": RUINS_PRODUCT_ID,
                "ruins_product_revision": RUINS_PRODUCT_REVISION,
                "ruins_canonical_home": True,
            },
        )
    context.validate_identity()
    action_executor = action_executor_factory(context)

    def attach_partial(exc):
        calls = getattr(action_executor, "transport_calls_by_category", {})
        challenge_calls = calls.get("challenge", 0) if isinstance(calls, dict) else 0
        chest_calls = calls.get("chest", 0) if isinstance(calls, dict) else 0
        partial = dict(getattr(exc, "partial_result", {}) or {})
        unresolved = route.unresolved_action or getattr(action_executor, "unresolved_action", False) is True
        partial.setdefault("status", "unresolved" if unresolved else "blocked")
        partial.setdefault("reason", f"ruins_native_route_failed:{type(exc).__name__}")
        partial.setdefault("ruins_dispatch_count", challenge_calls + chest_calls)
        partial.setdefault("challenge_transport_calls", challenge_calls)
        partial.setdefault("chest_claim_transport_calls", chest_calls)
        partial.setdefault("unresolved_action", unresolved)
        partial.setdefault("challenge_stages", list(route.challenge_stages))
        partial.setdefault("newly_claimed_chests", list(route.newly_claimed_chests))
        setattr(exc, "partial_result", partial)
        return exc

    route = RuinsIntegratedRoute(
        context.runtime,
        reset_identity=identity.reset_id,
        current_day=current_day,
        account_id=account_id,
        server_id=server_id,
        runtime_scope=runtime_scope,
        product_id=RUINS_PRODUCT_ID,
        product_revision=RUINS_PRODUCT_REVISION,
        runtime_identity=runtime_identity,
        action_executor=action_executor,
        initial_capture=initial,
        post_input_delay=context.settle_seconds,
    )
    try:
        outcome = route.run()
    except Exception as exc:
        try:
            adopt_ruins_route_transports(context)
        except Exception as accounting_exc:
            partial = dict(getattr(exc, "partial_result", {}) or {})
            partial.setdefault("accounting_error", f"{type(accounting_exc).__name__}: {accounting_exc}")
            setattr(exc, "partial_result", partial)
        raise attach_partial(exc)
    try:
        adopt_ruins_route_transports(context)
        context.validate_identity()
        home_reference = None
        if route.terminal_home_verified and route.terminal_home_capture is not None:
            home_frame, home_reference = context.capture_reference(
                route.terminal_home_capture.path,
                route.terminal_home_capture.sha256,
            )
            context.replay_source(home_frame, home_reference, "ruins-terminal-home")
            if not context.is_clean_home(home_frame.frame):
                raise ValueError("Ruins terminal Home capture is not canonical clean Home")
        accounting = context.accounting()
        calls = getattr(action_executor, "transport_calls_by_category", None)
        if calls != {
            "challenge": route.challenge_transport_calls,
            "chest": route.chest_claim_transport_calls,
        }:
            raise ValueError("Ruins route and canonical executor dispatch accounting differ")
        history_export = None
        history_export_error = None
        if route.confirmed_claim_records:
            try:
                history_export = write_continuation(
                    Path(context.runtime.session) / "ruins-chest-history.json",
                    reset_identity=identity.reset_id,
                    current_day=current_day,
                    claims=route.confirmed_claim_records,
                    evidence_root=Path(context.runtime.session),
                )
            except (OSError, ValueError) as exc:
                history_export_error = f"{type(exc).__name__}: {exc}"
        dispatch_count = route.challenge_transport_calls + route.chest_claim_transport_calls
        if dispatch_count > MAX_ACTIONS:
            raise ValueError("Ruins consequential dispatch budget exceeded")
    except Exception as exc:
        raise attach_partial(exc)
    return {
        "status": outcome.status,
        "reason": outcome.reason,
        "actions_completed": dispatch_count,
        "ruins_dispatch_count": dispatch_count,
        "challenge_transport_calls": route.challenge_transport_calls,
        "chest_claim_transport_calls": route.chest_claim_transport_calls,
        "challenge_stages": list(route.challenge_stages),
        "challenge_participation_confirmed": route.challenge_participation_confirmed,
        "daily_action_ready": route.daily_action_ready,
        "challenge_status": route.challenge_status,
        "unresolved_action": route.unresolved_action,
        "chest_status": route.chest_status,
        "newly_claimed_chests": list(route.newly_claimed_chests),
        "confirmed_claim_records": list(route.confirmed_claim_records),
        "history_export": history_export.name if history_export is not None else None,
        "history_export_error": history_export_error,
        "terminal_home_verified": bool(home_reference is not None and route.terminal_home_verified),
        "terminal_home_frame": (
            {
                "frame_path": home_reference.frame_path,
                "frame_sha256": home_reference.frame_sha256,
                "observed_utc": home_reference.observed_utc,
                "capture_ordinal": home_reference.capture_ordinal,
            }
            if home_reference is not None else None
        ),
        "input_count": accounting.input_count,
        "session_input_count": accounting.session_input_count,
        "runtime_input_count": accounting.runtime_input_count,
        "accounting_verified": accounting.verified,
        "scheduler_reset_id": identity.reset_id,
        "backend_reset_id": runtime_identity.reset_id,
        "runtime_scope": runtime_scope,
        "completed_at_utc": datetime.fromtimestamp(context.utc_clock(), timezone.utc).timestamp(),
        "session_directory": str(context.runtime.session),
    }


def create_service_binding(
    make_native_route_binding: Callable[..., NativeRouteBoundary],
) -> NativeRouteBoundary:
    """Build the fixed native lifecycle binding without opening a runtime."""

    if not callable(make_native_route_binding):
        raise TypeError("Ruins requires the injected native route binding factory")
    return make_native_route_binding(
        flow_id=RUINS_FLOW_ID,
        product_id=RUINS_PRODUCT_ID,
        product_revision=RUINS_PRODUCT_REVISION,
        runtime_profile_id=RUINS_PROFILE_ID,
        owner="automation-service:ruins-challenge",
        workflow="ruins-challenge-home-atlas",
        max_inputs=MAX_INPUTS,
        max_actions=MAX_ACTIONS,
        driver=execute_ruins_route,
    )
