#!/usr/bin/env python3
"""Executable, dry-run-by-default native BlueStacks route for Ruins Challenge."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bluestacks_native_runtime import IntegratedRouteResult, LocalBlueStacksRuntime, NativeRuntimePort
from scripts.home_atlas_bluestacks import BlueStacksLocalizeFirstHomeDriver, HomeDriverDisposition, ScrcpyMotionEventZoomTransport
from scripts.navigation_development_boundary import NavigationBoundaryError, NavigationGuardedRuntime, NavigationRouteDeclaration, make_source_safety_facts
from tasks.campaign_auto_battle import CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import recognize_campaign_frame
from tasks.home_atlas import load_home_atlas
from tasks.home_atlas_vision import BlueStacksHomeLocalizer, bind_visible_building
from tasks.home_context import HomeReadyObservation
from tasks.ruins_challenge import (
    KNOWN_CHALLENGE_IDENTITIES,
    RuinsAvailability,
    RuinsChestState,
    RuinsControlState,
    RuinsResult,
    current_day_allowed,
)
from tasks.ruins_challenge_runtime import RuinsRuntimeController
from tasks.ruins_challenge_vision import (
    recognize_ruins_detail_with_targets,
    recognize_ruins_frame,
    recognize_navigation_chat_screen,
    recognize_ruins_result_with_targets,
    recognize_ruins_reward_frame,
    recognize_any_ruins_reward_frame,
)
from tasks.runtime_identity import RuntimeIdentityAssurance, VerifiedRuntimeIdentity
from scripts.personal_might_praise_live import recognize_reset_popup


RUINS_HOME_ATLAS_BUILDING_ID = "home.building.ruins"
MAXIMUM_HOME_ZOOM_INPUTS = 4
HOME_RECOGNITION_PROBE_STAGE = CampaignStage(1, 1, 1)
_ORDINARY_RUINS_TARGETS = frozenset(
    {"ruins-attack", "ruins-dispatch", "ruins-result-continue", "ruins-reward-claim", "reset-popup-close"}
)


def ruins_challenge_navigation_route_declaration() -> NavigationRouteDeclaration:
    return NavigationRouteDeclaration(
        allowed_source_states=frozenset({"HOME_BASE", "RUINS_CHALLENGE", "RUINS_CHALLENGE_DETAIL", "RUINS_DISPATCH_DETAIL", "CHAT"}),
        allowed_target_identities=frozenset(
            {RUINS_HOME_ATLAS_BUILDING_ID, "home-zoom-out", "system-back"}
        ),
        allowed_gesture_classes=frozenset({"tap", "back", "zoom_out"}),
    )


class RuinsIntegratedRoute:
    """Drive one bounded challenge and optional independently reconciled Ruins chests."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        reset_identity: str,
        current_day: str,
        claim_chests: bool = False,
        chests_only: bool = False,
        allow_optional_second: bool = False,
        excluded_challenges: set[str] | None = None,
        navigation_only: bool = False,
        home_driver: BlueStacksLocalizeFirstHomeDriver | None = None,
        zoom_transport=None,
        post_input_delay: float = 1.0,
        recognition_timeout: float = 25.0,
    ) -> None:
        declaration = ruins_challenge_navigation_route_declaration()
        if zoom_transport is None and getattr(runtime, "execute", False):
            runner = getattr(runtime, "runner", None)
            if runner is not None:
                zoom_transport = ScrcpyMotionEventZoomTransport(
                    adb=runner.executable,
                    serial=runner.serial,
                    evidence_directory=getattr(runtime, "session", None),
                )
        self.runtime: NativeRuntimePort = runtime if isinstance(runtime, NavigationGuardedRuntime) else NavigationGuardedRuntime(runtime, declaration)
        self.reset_identity = reset_identity
        self.current_day = current_day
        self.claim_chests = claim_chests or chests_only
        self.chests_only = chests_only
        self.allow_optional_second = allow_optional_second
        self.navigation_only = navigation_only
        self.post_input_delay = post_input_delay
        self.recognition_timeout = recognition_timeout
        self.resource_delta = 0
        self._points_balance: int | None = None
        self.atlas_path = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
        self.atlas = load_home_atlas(self.atlas_path)
        identity = VerifiedRuntimeIdentity(
            "bluestacks-ruins-challenge", "supervised-ruins-challenge",
            "supervised-ruins-challenge-server", reset_identity,
            RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING, (f"reset:{reset_identity}",),
        )
        self.home_driver = home_driver or BlueStacksLocalizeFirstHomeDriver(
            self.atlas, self.atlas_path, HomeReadyObservation(True, True, identity, False, False),
            RUINS_HOME_ATLAS_BUILDING_ID, maximum_zoom_inputs=MAXIMUM_HOME_ZOOM_INPUTS,
        )
        self.zoom_transport = zoom_transport
        self.controller = RuinsRuntimeController(
            reset_identity=reset_identity,
            allow_optional_second=allow_optional_second,
        )
        self.controller.challenge_identities_attempted.update(excluded_challenges or set())

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

    def _dismiss_known_vip_popup(self, captured):
        """Close the retained benign VIP-points modal once when positively recognized."""
        detail = recognize_reset_popup(captured.frame)
        if not detail.get("recognized") or not detail.get("target"):
            return captured, None, 0
        self._ordinary_tap(
            captured,
            target_identity="reset-popup-close",
            target_roi=tuple(detail["target"]),
            action_key=f"ruins:vip-popup-close:{captured.sha256}",
            consequential=False,
        )
        time.sleep(self.post_input_delay)
        settled = self.runtime.capture("ruins-vip-popup-close-immediate-post")
        if recognize_reset_popup(settled.frame).get("recognized"):
            return settled, "vip_popup_close_successor_not_recognized", 1
        return settled, None, 1

    def _recover_home_zoom_before_ruins_binding(self) -> tuple[object | None, str | None]:
        """Reuse the accepted LocalizeFirst recovery before the current-frame bind."""
        for ordinal in range(1, MAXIMUM_HOME_ZOOM_INPUTS + 1):
            before = self.runtime.capture(f"ruins-home-zoom-{ordinal:02d}-immediate-before")
            step = self.home_driver.observe(before.frame)
            independent_home = (
                recognize_campaign_frame(before.frame, HOME_RECOGNITION_PROBE_STAGE).observation.screen
                is CampaignScreen.HOME_BASE
            )
            independently_authorized_unknown_zoom = bool(
                independent_home
                and step.disposition is HomeDriverDisposition.BLOCKED
                and step.reason == "home_localization_ambiguous:unknown"
            )
            if step.disposition in {HomeDriverDisposition.COMPLETE, HomeDriverDisposition.BIND, HomeDriverDisposition.PAN}:
                return before, None
            if step.disposition is HomeDriverDisposition.BLOCKED and not independently_authorized_unknown_zoom:
                return None, f"home_zoom_recovery_blocked:{step.reason}"
            if step.disposition is not HomeDriverDisposition.RECOVER_ZOOM and not independently_authorized_unknown_zoom:
                return None, f"home_zoom_recovery_unsupported:{step.disposition.value}"
            try:
                self.runtime.dispatch_zoom_out(
                    before,
                    make_source_safety_facts(
                        recognized=True, source_state="HOME_BASE", frame_sha256=before.sha256,
                        captured_monotonic=before.captured_monotonic,
                    ),
                    transport=(
                        self.zoom_transport.zoom_out_once
                        if self.zoom_transport is not None
                        else None
                    ),
                )
                if step.disposition is HomeDriverDisposition.RECOVER_ZOOM:
                    self.home_driver.record_zoom_input_dispatched(step.source_frame_sha256)
            except NavigationBoundaryError as exc:
                return None, str(exc)
            except Exception as exc:
                return None, f"android_zoom_transport_failed:{type(exc).__name__}:{exc}"
            immediate_post = self.runtime.capture(f"ruins-home-zoom-{ordinal:02d}-immediate-post")
            post_step = self.home_driver.observe(immediate_post.frame)
            if post_step.disposition is HomeDriverDisposition.BLOCKED:
                post_independent_home = (
                    recognize_campaign_frame(immediate_post.frame, HOME_RECOGNITION_PROBE_STAGE).observation.screen
                    is CampaignScreen.HOME_BASE
                )
                if post_independent_home and post_step.reason == "home_localization_ambiguous:unknown":
                    continue
                return None, f"home_zoom_post_reclassification_blocked:{post_step.reason}"
            if post_step.disposition in {HomeDriverDisposition.COMPLETE, HomeDriverDisposition.BIND, HomeDriverDisposition.PAN}:
                return immediate_post, None
        return None, "home_zoom_recovery_exhausted"

    def _recover_known_chat_to_home(self, source) -> tuple[object | None, str | None, int]:
        if not recognize_navigation_chat_screen(source.frame):
            return source, None, 0
        immediate_before = self.runtime.capture("ruins-chat-safe-exit-immediate-before")
        if not recognize_navigation_chat_screen(immediate_before.frame):
            return None, "chat_safe_exit_revalidation_failed", 0
        try:
            self._prepare_navigation(immediate_before, source_state="CHAT")
            self.runtime.back(
                immediate_before,
                action_key=f"ruins:chat-safe-exit:{immediate_before.sha256}",
            )
        except NavigationBoundaryError as exc:
            return None, str(exc), 0
        time.sleep(self.post_input_delay)
        immediate_post = self.runtime.capture("ruins-chat-safe-exit-immediate-post")
        home_step = self.home_driver.observe(immediate_post.frame)
        if home_step.disposition is HomeDriverDisposition.BLOCKED:
            return None, f"chat_safe_exit_home_not_recognized:{home_step.reason}", 1
        return immediate_post, None, 1

    def _recover_known_detail_to_list(self, source):
        """Safely back out of one positively recognized Ruins detail screen."""
        dispatch_probe = recognize_ruins_detail_with_targets(
            source.frame, "", reset_identity=self.reset_identity,
        )
        dispatch_observation = dispatch_probe.observation
        if (
            dispatch_observation.recognized
            and dispatch_observation.dispatch_control == RuinsControlState.VISIBLE_ENABLED
            and dispatch_observation.npc_troops_provided
            and dispatch_observation.npc_troops_current == dispatch_observation.npc_troops_maximum
            and dispatch_observation.skip_battle_enabled
        ):
            dispatch_before = self.runtime.capture("ruins-dispatch-safe-exit-immediate-before")
            dispatch_rebound = recognize_ruins_detail_with_targets(
                dispatch_before.frame, "", reset_identity=self.reset_identity,
            ).observation
            if not (
                dispatch_rebound.recognized
                and dispatch_rebound.dispatch_control == RuinsControlState.VISIBLE_ENABLED
                and dispatch_rebound.npc_troops_current == dispatch_rebound.npc_troops_maximum
                and dispatch_rebound.skip_battle_enabled
            ):
                return dispatch_before, None, 0, "ruins_dispatch_safe_exit_revalidation_failed", True
            try:
                self._prepare_navigation(dispatch_before, source_state="RUINS_DISPATCH_DETAIL")
                self.runtime.back(
                    dispatch_before,
                    action_key=f"ruins:dispatch-safe-exit:{dispatch_before.sha256}",
                )
            except NavigationBoundaryError as exc:
                return dispatch_before, None, 0, str(exc), True
            time.sleep(self.post_input_delay)
            detail_after = self.runtime.capture("ruins-dispatch-safe-exit-immediate-post")
            detail_candidates = []
            for identity in KNOWN_CHALLENGE_IDENTITIES:
                detail = recognize_ruins_detail_with_targets(
                    detail_after.frame, identity, reset_identity=self.reset_identity,
                )
                if detail.observation.recognized:
                    detail_candidates.append(identity)
            if len(detail_candidates) != 1:
                return detail_after, None, 1, "ruins_dispatch_safe_exit_detail_not_recognized", True
            list_capture, list_recognition, detail_actions, detail_error, detail_handled = self._recover_known_detail_to_list(detail_after)
            if not detail_handled:
                return detail_after, None, 1, "ruins_dispatch_safe_exit_detail_not_recognized", True
            if detail_error is not None:
                return list_capture, list_recognition, detail_actions + 1, detail_error, True
            return list_capture, list_recognition, detail_actions + 1, None, True
        if (
            dispatch_observation.npc_troops_provided
            or dispatch_observation.npc_troops_current is not None
            or dispatch_observation.skip_battle_enabled
        ):
            return source, None, 0, "ruins_dispatch_context_ambiguous", True
        candidates = []
        ambiguous_detail = False
        for identity in KNOWN_CHALLENGE_IDENTITIES:
            detail = recognize_ruins_detail_with_targets(
                source.frame, identity, reset_identity=self.reset_identity,
            )
            if detail.observation.recognized:
                candidates.append((identity, detail))
            elif detail.observation.floor_maximum > 0:
                ambiguous_detail = True
        if len(candidates) > 1:
            return source, None, 0, "ruins_detail_identity_ambiguous", True
        if not candidates:
            if ambiguous_detail:
                return source, None, 0, "ruins_detail_context_ambiguous", True
            return source, None, 0, None, False
        identity, _detail = candidates[0]
        immediate_before = self.runtime.capture("ruins-detail-safe-exit-immediate-before")
        rebound = recognize_ruins_detail_with_targets(
            immediate_before.frame, identity, reset_identity=self.reset_identity,
        )
        if not rebound.observation.recognized:
            return immediate_before, None, 0, "ruins_detail_safe_exit_revalidation_failed", True
        try:
            self._prepare_navigation(immediate_before, source_state="RUINS_CHALLENGE_DETAIL")
            self.runtime.back(
                immediate_before,
                action_key=f"ruins:detail-safe-exit:{immediate_before.sha256}",
            )
        except NavigationBoundaryError as exc:
            return immediate_before, None, 0, str(exc), True
        time.sleep(self.post_input_delay)
        settled, successor = self._observe_list("ruins-detail-safe-exit-immediate-post")
        if not successor.observation.recognized or successor.observation.screen_identity != "RUINS_CHALLENGE":
            return settled, successor, 1, "ruins_detail_safe_exit_successor_not_recognized", True
        return settled, successor, 1, None, True

    def _return_home(self, captured, recognition, actions: int) -> IntegratedRouteResult:
        if recognition.observation.home_base_recognized or self._home_atlas_recognized(captured.frame):
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
        exit_actions = actions + (1 if self.navigation_only else 0)
        if not successor.observation.home_base_recognized and not self._home_atlas_recognized(settled.frame):
            return IntegratedRouteResult("blocked", "safe_exit_home_successor_not_recognized", exit_actions, str(self.runtime.session))
        return IntegratedRouteResult("completed", "verified_safe_exit_to_home", exit_actions, str(self.runtime.session))

    def _home_atlas_recognized(self, frame) -> bool:
        return bool(BlueStacksHomeLocalizer(self.atlas, self.atlas_path).localize(frame).recognized)

    def recover_only(self, evidence_session: Path) -> IntegratedRouteResult:
        """Close one evidence-bound post-success detail without repeating combat."""
        flow_root = (ROOT / ".local-captures" / "flow-delivery" / "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION").resolve()
        try:
            evidence_session = evidence_session.resolve()
            evidence_session.relative_to(flow_root)
        except (OSError, ValueError):
            return IntegratedRouteResult("blocked", "recovery_evidence_session_outside_ruins_flow", 0, str(self.runtime.session))

        def evidence_path(row):
            raw = row.get("path")
            if not raw:
                return None
            try:
                path = Path(raw).resolve()
                path.relative_to(evidence_session)
                path.relative_to(evidence_session / "frames")
            except (OSError, ValueError):
                return None
            return path

        try:
            delivery = json.loads((evidence_session / "flow-delivery-result.json").read_text(encoding="utf-8"))
            events = [
                json.loads(line)
                for line in (evidence_session / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return IntegratedRouteResult("blocked", f"recovery_evidence_unreadable:{type(exc).__name__}", 0, str(self.runtime.session))
        for row in events:
            for field in ("path", "post_path"):
                if row.get(field) is not None:
                    try:
                        referenced = Path(row[field]).resolve()
                        referenced.relative_to(evidence_session)
                        referenced.relative_to(evidence_session / "frames")
                    except (OSError, TypeError, ValueError):
                        return IntegratedRouteResult("blocked", "recovery_evidence_path_escape", 0, str(self.runtime.session))
        if delivery.get("status") != "failed" or (delivery.get("ruins_result") or {}).get("reason") != "successful_progress_not_visible":
            return IntegratedRouteResult("blocked", "recovery_evidence_not_terminal_success_gap", 0, str(self.runtime.session))
        dispatches = [
            (index, row) for index, row in enumerate(events)
            if row.get("type") == "dispatch" and row.get("target_identity") == "ruins-dispatch" and row.get("consequential")
        ]
        if len(dispatches) != 1:
            return IntegratedRouteResult("blocked", "recovery_evidence_missing_consequential_dispatch", 0, str(self.runtime.session))
        dispatch_index, dispatch = dispatches[0]
        dispatch_key = dispatch.get("action_key")
        source_sha = dispatch.get("source_sha256")
        roi = dispatch.get("target_roi")
        if not isinstance(dispatch_key, str) or not dispatch_key or not isinstance(source_sha, str) or len(source_sha) != 64:
            return IntegratedRouteResult("blocked", "recovery_evidence_dispatch_binding_invalid", 0, str(self.runtime.session))
        if not (isinstance(roi, list) and len(roi) == 4 and all(isinstance(value, int) for value in roi)):
            return IntegratedRouteResult("blocked", "recovery_evidence_dispatch_target_invalid", 0, str(self.runtime.session))
        source_captures = []
        if dispatch_index > 0:
            source_row = events[dispatch_index - 1]
            source_path = evidence_path(source_row)
            if source_row.get("type") == "capture" and source_row.get("sha256") == source_sha and source_path is not None and hashlib.sha256(source_path.read_bytes()).hexdigest() == source_sha:
                source_captures.append(source_row)
        if len(source_captures) != 1:
            return IntegratedRouteResult("blocked", "recovery_evidence_dispatch_source_invalid", 0, str(self.runtime.session))
        continues = [
            (index, row) for index, row in enumerate(events)
            if index > dispatch_index and row.get("type") == "dispatch"
            and row.get("target_identity") == "ruins-result-continue"
            and row.get("action_key", "").startswith(dispatch_key + ":")
        ]
        if len(continues) != 1:
            return IntegratedRouteResult("blocked", "recovery_evidence_continue_link_invalid", 0, str(self.runtime.session))
        continue_index, continue_row = continues[0]
        successor_rows = [
            (index, row) for index, row in enumerate(events)
            if index > continue_index and row.get("type") == "capture" and row.get("label") == "challenge-list-postcondition"
        ]
        if len(successor_rows) != 1:
            return IntegratedRouteResult("blocked", "recovery_evidence_successor_link_invalid", 0, str(self.runtime.session))
        successor_index, successor_row = successor_rows[0]
        successor_path = evidence_path(successor_row)
        successor_sha = successor_row.get("sha256")
        if successor_path is None or not successor_path.is_file() or not isinstance(successor_sha, str) or len(successor_sha) != 64:
            return IntegratedRouteResult("blocked", "recovery_evidence_successor_frame_invalid", 0, str(self.runtime.session))
        if hashlib.sha256(successor_path.read_bytes()).hexdigest() != successor_sha:
            return IntegratedRouteResult("blocked", "recovery_evidence_successor_hash_mismatch", 0, str(self.runtime.session))
        reconciles = [
            (index, row) for index, row in enumerate(events)
            if index > successor_index and row.get("type") == "reconcile"
            and row.get("status") == "unresolved" and row.get("reason") == "successful row progress not visible"
            and row.get("action_key") == dispatch_key
            and row.get("post_path") and Path(row.get("post_path")).resolve() == successor_path
            and row.get("post_sha256") == successor_sha
        ]
        if len(reconciles) != 1:
            return IntegratedRouteResult("blocked", "recovery_evidence_reconcile_link_invalid", 0, str(self.runtime.session))
        detail_rows = [
            (index, row) for index, row in enumerate(events)
            if row.get("type") == "capture" and row.get("label") == "challenge-detail-immediate-post" and index < dispatch_index
        ]
        if len(detail_rows) != 1:
            return IntegratedRouteResult("blocked", "recovery_evidence_detail_frame_invalid", 0, str(self.runtime.session))
        _detail_index, detail_row = detail_rows[0]
        detail_path = evidence_path(detail_row)
        if detail_path is None or not detail_path.is_file() or detail_row.get("sha256") != hashlib.sha256(detail_path.read_bytes()).hexdigest():
            return IntegratedRouteResult("blocked", "recovery_evidence_detail_hash_mismatch", 0, str(self.runtime.session))
        successor_frame = cv2.imread(str(successor_path))
        if successor_frame is None or successor_frame.shape[:2] != (1280, 800):
            return IntegratedRouteResult("blocked", "recovery_evidence_successor_frame_invalid", 0, str(self.runtime.session))
        detail_frame = cv2.imread(str(detail_path))
        prior_candidates = []
        for identity in KNOWN_CHALLENGE_IDENTITIES:
            detail = recognize_ruins_detail_with_targets(detail_frame, identity, reset_identity=self.reset_identity)
            if detail.observation.recognized:
                prior_candidates.append((identity, detail.observation.floor_current, detail.observation.floor_maximum))
        if len(prior_candidates) != 1:
            return IntegratedRouteResult("blocked", "recovery_evidence_detail_identity_ambiguous", 0, str(self.runtime.session))
        prior_identity, prior_floor, prior_maximum = prior_candidates[0]
        candidates = []
        detail = recognize_ruins_detail_with_targets(successor_frame, prior_identity, reset_identity=self.reset_identity)
        if detail.observation.recognized:
            candidates.append((prior_identity, detail.observation.floor_current, detail.observation.floor_maximum))
        if len(candidates) != 1 or candidates[0][0] != prior_identity or candidates[0][1] != prior_floor + 1 or candidates[0][2] != prior_maximum:
            return IntegratedRouteResult("blocked", "recovery_evidence_successor_detail_ambiguous", 0, str(self.runtime.session))
        identity, successor_floor, successor_maximum = candidates[0]
        source = self.runtime.capture("ruins-recovery-source")
        current_candidates = []
        detail = recognize_ruins_detail_with_targets(source.frame, prior_identity, reset_identity=self.reset_identity)
        if detail.observation.recognized:
            current_candidates.append((prior_identity, detail.observation.floor_current, detail.observation.floor_maximum))
        if current_candidates != [(identity, successor_floor, successor_maximum)]:
            return IntegratedRouteResult("blocked", "recovery_current_detail_does_not_match_retained_successor", 0, str(self.runtime.session))
        # Bind this continuation to the already-attempted identity so a recovery
        # invocation cannot fall through into a fresh challenge selection.
        self.controller.challenge_identities_attempted.add(identity)
        captured, recognition, _actions, error, handled = self._recover_known_detail_to_list(source)
        if not handled or error is not None:
            return IntegratedRouteResult("blocked", error or "recovery_detail_to_list_failed", 0, str(self.runtime.session))
        return self._return_home(captured, recognition, 0)

    def _current_frame_ruins_binding(self, captured):
        localization = BlueStacksHomeLocalizer(self.atlas, self.atlas_path).localize(captured.frame)
        if not localization.recognized:
            return None
        binding = bind_visible_building(
            captured.frame,
            localization,
            self.atlas.lookup_building(RUINS_HOME_ATLAS_BUILDING_ID),
        )
        if (
            binding is None
            or binding.building_id != RUINS_HOME_ATLAS_BUILDING_ID
            or binding.frame_sha256 != localization.frame_sha256
            or binding.overlay_intersects
            or binding.ambiguous_overlap
        ):
            return None
        return tuple(binding.target_roi)

    def _claim_one_chest(self, captured, recognition):
        observation = recognition.observation
        for row in observation.rows:
            if row.chest_state != RuinsChestState.AVAILABLE:
                continue
            target_identity = f"chest:{row.identity}"
            target = recognition.target(target_identity)
            if target is None:
                return "blocked", "available_chest_target_not_bound", captured, recognition
            action_key = f"ruins:chest:{self.reset_identity}:{row.identity}:{captured.sha256}"
            command = self.controller.plan_chest_claim(observation, row, action_key=action_key)
            if command.kind != "claim_chest":
                return "blocked", command.reason, captured, recognition
            self._ordinary_tap(
                captured,
                target_identity=target_identity,
                target_roi=target,
                action_key=action_key,
                consequential=False,
            )
            time.sleep(self.post_input_delay)
            modal_capture = self.runtime.capture("chest-modal-immediate-post")
            modal = recognize_ruins_reward_frame(modal_capture.frame, row.identity, reset_identity=self.reset_identity)
            claim_target = modal.target("ruins-reward-claim")
            if not modal.recognized or claim_target is None:
                self.runtime.reconcile(action_key, "unresolved", modal_capture, "Ruins reward modal not positively recognized")
                return "unresolved", "chest_reward_modal_not_recognized", modal_capture, recognition
            self._ordinary_tap(
                modal_capture,
                target_identity="ruins-reward-claim",
                target_roi=claim_target,
                action_key=f"{action_key}:claim",
            )
            time.sleep(self.post_input_delay)
            post_capture, post_recognition = self._observe_list("chest-claim-immediate-post")
            after = post_recognition.observation.row(row.identity)
            chest_target_absent = post_recognition.target(target_identity) is None
            if not post_recognition.observation.recognized or after is None or not chest_target_absent:
                self.runtime.reconcile(action_key, "unresolved", post_capture, "exact chest disappearance not proven")
                return "unresolved", "chest_postcondition_not_proven", post_capture, post_recognition
            after = replace(after, chest_state=RuinsChestState.CLAIMED)
            reconciled = self.controller.reconcile_chest(row, after, action_key=action_key)
            if reconciled.kind != "chest_reconciled":
                self.runtime.reconcile(action_key, "unresolved", post_capture, reconciled.reason)
                return "unresolved", reconciled.reason, post_capture, post_recognition
            self.runtime.reconcile(action_key, "confirmed", post_capture, "exact Ruins chest disappeared after Claim")
            after_points = post_recognition.observation.points_balance
            before_points = observation.points_balance if observation.points_balance is not None else self._points_balance
            if before_points is not None and after_points is not None and after_points >= before_points:
                self.resource_delta += after_points - before_points
            if after_points is not None:
                self._points_balance = after_points
            return "claimed", row.identity, post_capture, post_recognition
        return "none", "no_available_chest", captured, recognition

    def _continue_open_reward_modal(self, captured, reward):
        target = reward.target("ruins-reward-claim")
        if not reward.recognized or target is None:
            return captured, None, 0, "ruins_reward_source_not_recognized"
        self._ordinary_tap(
            captured,
            target_identity="ruins-reward-claim",
            target_roi=target,
            action_key=f"ruins:reward-continuation:{self.reset_identity}:{reward.identity}:{captured.sha256}",
        )
        time.sleep(self.post_input_delay)
        post_capture, post_recognition = self._observe_list("reward-continuation-immediate-post")
        if (
            not post_recognition.observation.recognized
            or post_recognition.observation.screen_identity != "RUINS_CHALLENGE"
            or post_recognition.target(f"chest:{reward.identity}") is not None
        ):
            return post_capture, post_recognition, 0, "reward_continuation_postcondition_not_proven"
        if post_recognition.observation.points_balance is not None:
            self._points_balance = post_recognition.observation.points_balance
        return post_capture, post_recognition, 1, None

    def _choose_challenge(self, recognition):
        candidates = []
        for row in recognition.observation.rows:
            if (
                row.availability == RuinsAvailability.AVAILABLE
                and row.challenge_control == RuinsControlState.VISIBLE_ENABLED
                and current_day_allowed(row, self.current_day)
                and row.identity not in self.controller.challenge_identities_attempted
                and recognition.target(f"challenge:{row.identity}") is not None
            ):
                candidates.append(row)
        return candidates[0] if candidates else None

    def _run_challenge(self, captured, recognition, row):
        action_key = f"ruins:challenge:{self.reset_identity}:{row.identity}:{captured.sha256}"
        planned = self.controller.plan_challenge(
            recognition.observation,
            row,
            current_day=self.current_day,
            action_key=action_key,
        )
        if planned.kind != "open_detail":
            return IntegratedRouteResult("blocked", planned.reason, 0, str(self.runtime.session))
        target = recognition.target(f"challenge:{row.identity}")
        self._ordinary_tap(
            captured,
            target_identity=f"challenge:{row.identity}",
            target_roi=target or (0, 0, 0, 0),
            action_key=f"{action_key}:open",
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
            return IntegratedRouteResult("blocked", "detail or Attack target not positively recognized", 0, str(self.runtime.session))
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
        dispatch = self.controller.plan_dispatch(dispatch_observation, action_key=action_key)
        if dispatch.kind != "dispatch" or dispatch_target is None:
            return IntegratedRouteResult("blocked", "Dispatch target or zero-cost NPC contract not proven", 0, str(self.runtime.session))
        self._ordinary_tap(
            dispatch_capture,
            target_identity="ruins-dispatch",
            target_roi=dispatch_target,
            action_key=action_key,
            consequential=True,
        )
        deadline = time.monotonic() + self.recognition_timeout
        result_capture = None
        result_recognition = None
        while time.monotonic() < deadline:
            time.sleep(min(0.5, self.post_input_delay))
            candidate_capture = self.runtime.capture("challenge-result-immediate-post")
            candidate = recognize_ruins_result_with_targets(
                candidate_capture.frame,
                row.identity,
                before_progress=row.progress_current,
                reset_identity=self.reset_identity,
            )
            if candidate.observation.result != RuinsResult.AMBIGUOUS and candidate.target("ruins-result-continue") is not None:
                result_capture, result_recognition = candidate_capture, candidate
                break
        if result_capture is None or result_recognition is None:
            unresolved = self.runtime.capture("challenge-result-unresolved")
            self.runtime.reconcile(action_key, "unresolved", unresolved, "explicit result and safe continuation not recognized")
            return IntegratedRouteResult("unresolved", "challenge_result_not_recognized", 0, str(self.runtime.session))
        self._ordinary_tap(
            result_capture,
            target_identity="ruins-result-continue",
            target_roi=result_recognition.target("ruins-result-continue") or (0, 0, 0, 0),
            action_key=f"{action_key}:continue",
            continuation_of=action_key,
        )
        time.sleep(self.post_input_delay)
        list_capture, list_recognition = self._observe_list("challenge-list-postcondition")
        result_observation = result_recognition.observation
        if result_observation.result == RuinsResult.SUCCESS:
            after_row = list_recognition.observation.row(row.identity)
            if after_row is None:
                detail_successor = recognize_ruins_detail_with_targets(
                    list_capture.frame, row.identity, reset_identity=self.reset_identity,
                )
                detail_observation = detail_successor.observation
                if not (
                    detail_observation.recognized
                    and detail_observation.identity == row.identity
                    and detail_observation.reset_identity == self.reset_identity
                    and detail_observation.floor_current > row.progress_current
                    and detail_observation.floor_maximum == row.progress_maximum
                ):
                    self.runtime.reconcile(action_key, "unresolved", list_capture, "successful row progress not visible")
                    return IntegratedRouteResult("unresolved", "successful_progress_not_visible", 0, str(self.runtime.session))
                recovered_capture, recovered_recognition, _recovery_actions, recovery_error, recovery_handled = self._recover_known_detail_to_list(list_capture)
                if not recovery_handled or recovery_error is not None:
                    self.runtime.reconcile(action_key, "unresolved", recovered_capture, recovery_error or "successful detail successor safe exit not recognized")
                    return IntegratedRouteResult("unresolved", recovery_error or "successful_detail_successor_safe_exit_not_recognized", 0, str(self.runtime.session))
                list_capture, list_recognition = recovered_capture, recovered_recognition
                after_row = list_recognition.observation.row(row.identity)
                if after_row is None:
                    self.runtime.reconcile(action_key, "unresolved", list_capture, "successful detail successor list progress not visible")
                    return IntegratedRouteResult("unresolved", "successful_progress_not_visible", 0, str(self.runtime.session))
            result_observation = replace(
                result_observation,
                progress_after=after_row.progress_current,
                maximum_after=after_row.progress_maximum,
                level_after=after_row.progress_current,
            )
        reconciled = self.controller.reconcile_result(row, result_observation)
        if reconciled.kind != "reconciled":
            self.runtime.reconcile(action_key, "unresolved", list_capture, reconciled.reason)
            return IntegratedRouteResult("unresolved", reconciled.reason, 0, str(self.runtime.session))
        status = "confirmed" if result_observation.result == RuinsResult.SUCCESS else "failed_confirmed"
        self.runtime.reconcile(action_key, status, list_capture, f"explicit {result_observation.result.value} result reconciled")
        return list_capture, list_recognition, result_observation.result

    def run(self, *, max_steps: int = 30) -> IntegratedRouteResult:
        if not self.runtime.execute:
            captured = self.runtime.capture("dry-run-source")
            if recognize_navigation_chat_screen(captured.frame):
                return IntegratedRouteResult(
                    "dry-run",
                    "transport_disabled:chat_safe_exit_required",
                    0,
                    str(self.runtime.session),
                )
            preparation = self.home_driver.observe(captured.frame)
            if preparation.disposition is HomeDriverDisposition.RECOVER_ZOOM:
                return IntegratedRouteResult(
                    "dry-run",
                    "transport_disabled:home_zoom_recovery_required",
                    0,
                    str(self.runtime.session),
                )
            if preparation.disposition is HomeDriverDisposition.BLOCKED:
                independent_home = (
                    recognize_campaign_frame(captured.frame, HOME_RECOGNITION_PROBE_STAGE).observation.screen
                    is CampaignScreen.HOME_BASE
                )
                if independent_home and preparation.reason == "home_localization_ambiguous:unknown":
                    return IntegratedRouteResult(
                        "dry-run",
                        "transport_disabled:home_zoom_recovery_required",
                        0,
                        str(self.runtime.session),
                    )
                return IntegratedRouteResult(
                    "blocked",
                    f"home_zoom_recovery_blocked:{preparation.reason}",
                    0,
                    str(self.runtime.session),
                )
            home_binding = self._current_frame_ruins_binding(captured)
            status = "dry-run" if home_binding is not None else "blocked"
            reason = "transport_disabled:home_atlas_ruins_bound" if home_binding is not None else "home_atlas_ruins_not_bound"
            return IntegratedRouteResult(status, reason, 0, str(self.runtime.session))
        actions = 0
        source = self.runtime.capture("route-source")
        if self.chests_only:
            reward = recognize_any_ruins_reward_frame(source.frame, reset_identity=self.reset_identity)
            if reward.recognized:
                captured, recognition, reward_actions, reward_error = self._continue_open_reward_modal(source, reward)
                actions += reward_actions
                if reward_error is not None:
                    return IntegratedRouteResult("blocked", reward_error, actions, str(self.runtime.session))
                source = captured
                source_recognition = recognition
            else:
                source_recognition = None
        else:
            source_recognition = None
        _home_source, source_error, recovered_actions = self._recover_known_chat_to_home(source)
        actions += recovered_actions
        if source_error is not None:
            return IntegratedRouteResult("blocked", source_error, actions, str(self.runtime.session))
        source, popup_error, popup_actions = self._dismiss_known_vip_popup(source)
        actions += popup_actions
        if popup_error is not None:
            return IntegratedRouteResult("blocked", popup_error, actions, str(self.runtime.session))
        source_recognition = source_recognition or recognize_ruins_frame(source.frame, reset_identity=self.reset_identity)
        already_in_ruins = (
            source_recognition.observation.recognized
            and source_recognition.observation.screen_identity == "RUINS_CHALLENGE"
        )
        if already_in_ruins:
            # A development session may begin from a positively recognized Ruins
            # list after an earlier navigation handoff. Continue gameplay directly;
            # Home zoom/atlas entry is only required for Home-origin sessions.
            captured, recognition = source, source_recognition
        else:
            if source_recognition.observation.home_base_recognized:
                captured, recognition, detail_actions, detail_error, detail_handled = source, source_recognition, 0, None, False
            else:
                captured, recognition, detail_actions, detail_error, detail_handled = self._recover_known_detail_to_list(source)
            if detail_handled:
                actions += detail_actions
                if detail_error is not None:
                    return IntegratedRouteResult("blocked", detail_error, actions, str(self.runtime.session))
            else:
                _prepared, preparation_error = self._recover_home_zoom_before_ruins_binding()
                if preparation_error is not None:
                    return IntegratedRouteResult("blocked", preparation_error, actions, str(self.runtime.session))
                captured, recognition = self._observe_list("ruins-home-atlas-immediate-before")
                target = self._current_frame_ruins_binding(captured)
                if target is not None:
                    # The building can be off-screen at canonical Home. The Atlas binding is
                    # therefore the entry authority; the Ruins adapter is only used after entry.
                    try:
                        self._prepare_navigation(captured, source_state="HOME_BASE", target_roi=target)
                        self.runtime.tap(
                            captured, target_identity=RUINS_HOME_ATLAS_BUILDING_ID, target_roi=target,
                            action_key=f"ruins:open:{captured.sha256}",
                        )
                    except NavigationBoundaryError as exc:
                        return IntegratedRouteResult("blocked", str(exc), actions, str(self.runtime.session))
                    # Gameplay action accounting reports challenge/chest work; the
                    # navigation-only route retains its Home-entry input count.
                    if self.navigation_only:
                        actions += 1
                    time.sleep(self.post_input_delay)
                    captured, recognition = self._observe_list("ruins-list-immediate-post")
        if not recognition.observation.recognized or recognition.observation.screen_identity != "RUINS_CHALLENGE":
            return IntegratedRouteResult("blocked", "Ruins list not positively recognized", 0, str(self.runtime.session))
        self.controller.observe_list(recognition.observation)
        if recognition.observation.points_balance is not None and self._points_balance is None:
            self._points_balance = recognition.observation.points_balance
        if self.navigation_only:
            return self._return_home(captured, recognition, actions)
        if self.claim_chests:
            for _ in range(max_steps):
                chest_status, reason, captured, recognition = self._claim_one_chest(captured, recognition)
                if chest_status == "claimed":
                    actions += 1
                    self.controller.observe_list(recognition.observation)
                    continue
                if chest_status in {"blocked", "unresolved"}:
                    return IntegratedRouteResult(chest_status, reason, actions, str(self.runtime.session))
                break
        if self.chests_only:
            return self._return_home(captured, recognition, actions)
        row = self._choose_challenge(recognition)
        if row is None:
            return self._return_home(captured, recognition, actions)
        challenge_result = self._run_challenge(captured, recognition, row)
        if isinstance(challenge_result, IntegratedRouteResult):
            return challenge_result
        captured, recognition, result = challenge_result
        actions += 1
        if result == RuinsResult.FAILURE and self.allow_optional_second:
            self.controller.observe_list(recognition.observation)
            second_row = self._choose_challenge(recognition)
            if second_row is not None:
                second_result = self._run_challenge(captured, recognition, second_row)
                if isinstance(second_result, IntegratedRouteResult):
                    return IntegratedRouteResult(
                        second_result.status,
                        second_result.reason,
                        actions + second_result.actions_completed,
                        second_result.session_directory,
                    )
                captured, recognition, _ = second_result
                actions += 1
        return self._return_home(captured, recognition, actions)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--reset-identity", required=True)
    parser.add_argument("--current-day", required=True, choices=("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
    parser.add_argument("--claim-chests", action="store_true")
    parser.add_argument("--chests-only", action="store_true", help="claim visible Ruins chests and return Home without starting combat")
    parser.add_argument("--allow-optional-second", action="store_true")
    parser.add_argument("--navigation-only", action="store_true", help="permit only Home -> Ruins -> Home navigation")
    parser.add_argument("--recovery-only", action="store_true", help="close one evidence-bound post-success detail without combat")
    parser.add_argument("--recovery-session", type=Path, default=None, help="retained Ruins session bound to --recovery-only")
    parser.add_argument("--exclude-challenge", action="append", default=[])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm the exact local BlueStacks target non-interactively")
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/ruins-challenge-integrated"))
    args = parser.parse_args(argv)
    if args.execute and not args.yes:
        parser.error("--execute requires --yes")
    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="ruins-challenge",
        execute=args.execute,
    )
    route = RuinsIntegratedRoute(
        runtime,
        reset_identity=args.reset_identity,
        current_day=args.current_day,
        claim_chests=args.claim_chests,
        chests_only=args.chests_only,
        allow_optional_second=args.allow_optional_second,
        excluded_challenges=set(args.exclude_challenge),
        navigation_only=args.navigation_only,
    )
    if args.recovery_only:
        if args.recovery_session is None:
            parser.error("--recovery-only requires --recovery-session")
        result = route.recover_only(args.recovery_session)
    else:
        result = route.run()
    print(json.dumps({**result.__dict__, "resource_delta": route.resource_delta}, sort_keys=True))
    return 0 if result.status in {"completed", "dry-run"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
