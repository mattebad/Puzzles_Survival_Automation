#!/usr/bin/env python3
"""Executable, dry-run-by-default local BlueStacks route for Daily troop training."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bluestacks_native_runtime import IntegratedRouteResult, LocalBlueStacksRuntime, NativeRuntimePort
from tasks.troop_training import (
    FACILITY_BY_TYPE,
    RESOURCE_NAMES,
    TROOP_TYPES,
    TrainingConfig,
    TrainingController,
    TroopTrainingConfig,
    TrainingScreenObservation,
    expected_completion_timestamp,
    make_action_key,
)
from tasks.troop_training_runtime import TrainingPhase, TroopTrainingRuntimeController
from tasks.troop_training_vision import (
    QUANTITY_BAND,
    TAB_ROIS,
    recognize_auto_use_resource_popup,
    recognize_home,
    recognize_exit_dialog,
    recognize_radial_menu,
    recognize_training,
    recognize_training_with_targets,
)


RESOURCE_BOXES_APPLIED_REAPPLY_TRAINING = "resource boxes applied; reapply exact quantity and authorize a new Train transaction"


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
    session: str


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

    def __init__(self, runtime: NativeRuntimePort, *, post_input_delay: float = 1.0) -> None:
        self.runtime = runtime
        self.post_input_delay = post_input_delay

    def run(self) -> TroopTrainingReturnHomeResult:
        source = self.runtime.capture("return-home-source")
        exit_dialog, cancel_target = recognize_exit_dialog(source.frame)
        if exit_dialog and cancel_target is not None:
            self.runtime.tap(
                source,
                target_identity="exit-dialog-cancel",
                target_roi=cancel_target,
                action_key=f"training:navigation:exit-dialog-cancel:{source.sha256}",
            )
            time.sleep(self.post_input_delay)
            final = self.runtime.capture("return-home-final-after-cancel")
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
        home = recognize_home(source.frame, reset_identity="return-home")
        training = recognize_training(source.frame)
        if not home.recognized and not training:
            return TroopTrainingReturnHomeResult("blocked", "current surface is not positively recognized", 0, False, str(self.runtime.session))
        if home.recognized and not training.recognized:
            return TroopTrainingReturnHomeResult("completed", "already at recognized Home/Base", 0, True, str(self.runtime.session))
        # OCR can consume enough time to age the source frame. Rebind the navigation action on a
        # fresh frame and refuse to Back from a radial overlay or any other unknown surface.
        fresh = self.runtime.capture("return-home-fresh-before-back")
        fresh_home = recognize_home(fresh.frame, reset_identity="return-home")
        fresh_training = recognize_training(fresh.frame)
        if fresh_home.recognized and not fresh_training.recognized:
            return TroopTrainingReturnHomeResult("completed", "fresh frame is already at recognized Home/Base", 0, True, str(self.runtime.session))
        if not fresh_training.recognized:
            return TroopTrainingReturnHomeResult("blocked", "fresh frame is not a recognized training surface; no Back dispatched", 0, False, str(self.runtime.session))
        self.runtime.back(fresh, action_key=f"training:navigation:return-home-only:{fresh.sha256}")
        time.sleep(self.post_input_delay)
        final = self.runtime.capture("return-home-final")
        final_home = recognize_home(final.frame, reset_identity="return-home")
        if not final_home.recognized:
            return TroopTrainingReturnHomeResult("blocked", "native navigation did not prove Home/Base", 1, False, str(self.runtime.session))
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
    ) -> None:
        self.runtime = runtime
        self.config = config
        self.reset_identity = reset_identity
        self.post_input_delay = post_input_delay
        self.max_tier_swipes = max_tier_swipes
        self.controller = TroopTrainingRuntimeController(config, reset_identity=reset_identity)
        self.actions_completed = 0
        self.completed_claims: list[dict[str, object]] = []
        self.warehouse_approvals: list[dict[str, object]] = []
        self.resource_box_approvals: list[dict[str, object]] = []
        self.training: list[dict[str, object]] = []

    def _result(self, status: str, reason: str, *, final_home: bool = False) -> TroopTrainingRouteResult:
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
            session=str(self.runtime.session),
        )

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

    def _capture_radial(self, label: str, troop_type: str):
        last_captured = None
        last_observation = None
        for attempt in range(2):
            capture_label = label if attempt == 0 else f"{label}-recognition-retry-{attempt}"
            captured = self.runtime.capture(capture_label)
            observation = recognize_radial_menu(captured.frame, troop_type=troop_type)
            last_captured, last_observation = captured, observation
            if observation.recognized:
                return captured, observation
        return last_captured, last_observation

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
            consequential=True,
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
        return post_capture, post, None

    def _switch_tab(self, captured, observation: TrainingScreenObservation, troop_type: str):
        if observation.troop_type == troop_type:
            return captured, observation, None
        captured, observation, error = self._claim_completed_tab(captured, observation)
        if error:
            return None, None, error
        recognition = recognize_training_with_targets(captured.frame)
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
                self._navigation_tap(
                    captured,
                    identity=f"tier:{config.target_tier}",
                    roi=candidate.target_roi,
                    action_key=f"training:navigation:tier:{troop_type}:{config.target_tier}:{captured.sha256}",
                )
                post_capture, post = self._capture_training(f"tier-{troop_type}-post")
                selected = post.tier(config.target_tier)
                if not post.recognized or post.selected_tier != config.target_tier or selected is None or selected.locked:
                    return None, None, "configured tier selection was not positively verified"
                return post_capture, post, None
            window = tuple(item.tier for item in observation.visible_tiers)
            if not window or window in seen_windows or ordinal == self.max_tier_swipes:
                return None, None, "tier carousel repeated, had no progress, or exceeded bound"
            seen_windows.add(window)
            minimum, maximum = min(window), max(window)
            if config.target_tier > maximum:
                start, end = (650, 900), (150, 900)
            elif config.target_tier < minimum:
                start, end = (150, 900), (650, 900)
            else:
                return None, None, "configured tier lies in an unrecognized carousel gap"
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
        return None, None, "tier selection stopped safely"

    def _set_quantity(self, captured, observation: TrainingScreenObservation, troop_type: str):
        quantity = self.config.for_type(troop_type).quantity
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
        max_digits = len(str(observation.quantity_maximum or 1000))
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
        # Fresh immediate-before capture is mandatory even when the previous navigation produced
        # a visually identical frame.
        captured = self.runtime.capture(f"{troop_type}-train-immediate-before")
        observation = recognize_training(captured.frame)
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
            # Rebind both buttons and every resource amount from a fresh native frame before the
            # one permitted continuation input.  Confirm is never inferred from the stale
            # immediate-post frame.
            popup_capture = self.runtime.capture(f"{troop_type}-resource-box-popup-immediate-before")
            resource_popup = recognize_auto_use_resource_popup(popup_capture.frame)
            popup_plan = self.controller.semantic.plan_resource_box_continuation(
                observation,
                resource_popup,
                troop_type,
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
                    "configured_quantity": self.config.for_type(troop_type).quantity,
                    "popup_frame_hash": popup_capture.sha256,
                    "post_frame_hash": confirmed_capture.sha256,
                    "resources_after_use": [asdict(resource) for resource in resource_popup.resources_after_use],
                }
                if (
                    confirmed.recognized
                    and confirmed.queue_active
                    and confirmed.troop_type == troop_type
                    and confirmed.selected_tier == observation.selected_tier
                    and confirmed.selected_quantity == self.config.for_type(troop_type).quantity
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
                "quantity": state.configured_quantity,
                "reset_identity": state.reset_identity,
                "action_key": action_key,
                "source_frame_hash": captured.sha256,
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
        self.runtime.back(captured, action_key=f"training:navigation:return-home:{captured.sha256}")
        self.actions_completed += 1
        self._wait()
        final_capture, final_home = self._capture_home("final-home")
        if not final_home.recognized:
            return self._result("blocked", "final Home/Base postcondition not recognized")
        self.controller.final_home()
        return self._result(status, reason, final_home=True)

    def _run_training_tabs(self, captured, observation: TrainingScreenObservation, enabled_types: list[str], first: str) -> TroopTrainingRouteResult:
        self.controller.begin_facility(first, captured.sha256)
        for troop_type in enabled_types:
            captured, observation, error = self._switch_tab(captured, observation, troop_type)
            if error:
                return self._result("unresolved" if self.runtime.in_flight_action else "blocked", error)
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

    def run_from_current_radial(self, first: str) -> TroopTrainingRouteResult:
        """Continue a recognized current radial into one training view, then use tabs only."""

        self.config.validate()
        if not self.runtime.execute:
            return self._result("dry-run", "dry-run-no-input; native runtime issued no input")
        enabled_types = [
            troop_type
            for troop_type in TROOP_TYPES
            if self.config.for_type(troop_type).enabled and self.config.for_type(troop_type).training_policy != "disabled"
        ]
        if first not in enabled_types:
            return self._result("blocked", f"radial continuation type {first!r} is not enabled")
        try:
            menu_capture, menu = self._capture_radial("continuation-radial", first)
            if not menu.recognized or menu.train_target is None:
                return self._result("blocked", f"{first} radial menu or Train control not recognized")
            self._navigation_tap(
                menu_capture,
                identity=f"train-menu:{first}",
                roi=menu.train_target,
                action_key=f"training:navigation:train-menu:{first}:{menu_capture.sha256}",
            )
            captured, observation = self._capture_training("continuation-training-screen-source")
            if not observation.recognized or observation.troop_type != first:
                return self._result("blocked", "complete training screen not recognized after radial continuation")
            return self._run_training_tabs(captured, observation, enabled_types, first)
        except Exception as exc:
            if self.runtime.in_flight_action is not None:
                return self._result("unresolved", f"runtime failure after consequential action: {exc}")
            return self._result("blocked", f"safe radial continuation stop: {exc}")

    def run_from_current_training(self, first: str) -> TroopTrainingRouteResult:
        """Continue a recognized current training view using its four troop tabs only."""

        self.config.validate()
        if not self.runtime.execute:
            return self._result("dry-run", "dry-run-no-input; native runtime issued no input")
        enabled_types = [
            troop_type
            for troop_type in TROOP_TYPES
            if self.config.for_type(troop_type).enabled and self.config.for_type(troop_type).training_policy != "disabled"
        ]
        if first not in enabled_types:
            return self._result("blocked", f"training continuation type {first!r} is not enabled")
        captured, observation = self._capture_training("continuation-current-training")
        if not observation.recognized or observation.troop_type != first:
            return self._result("blocked", "current training view did not positively recognize the configured troop type")
        return self._run_training_tabs(captured, observation, enabled_types, first)

    def run(self) -> TroopTrainingRouteResult:
        self.config.validate()
        home_capture, home = self._capture_home("home-source")
        if not home.recognized:
            return self._result("blocked", "Home/Base and all four facilities not positively recognized")
        if not self.runtime.execute:
            return self._result("dry-run", "dry-run-no-input; native runtime issued no input")
        enabled_types = [troop_type for troop_type in TROOP_TYPES if self.config.for_type(troop_type).enabled and self.config.for_type(troop_type).training_policy != "disabled"]
        if not enabled_types:
            return self._result("completed", "all troop workflows disabled; no input authorized", final_home=True)
        first = enabled_types[0]
        facility_target = home.facility_target(first)
        if facility_target is None:
            return self._result("blocked", f"{first} facility target not bound")
        try:
            self._navigation_tap(
                home_capture,
                identity=f"facility:{first}",
                roi=facility_target,
                action_key=f"training:navigation:facility:{first}:{home_capture.sha256}",
            )
            menu_capture, menu = self._capture_radial("facility-radial-menu", first)
            if not menu.recognized or menu.train_target is None:
                return self._result("blocked", f"{first} radial menu or Train control not recognized")
            self._navigation_tap(
                menu_capture,
                identity=f"train-menu:{first}",
                roi=menu.train_target,
                action_key=f"training:navigation:train-menu:{first}:{menu_capture.sha256}",
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
        values = {}
        for troop_type in TROOP_TYPES:
            item = payload.get(troop_type, {})
            values[troop_type] = TrainingConfig(
                enabled=item.get("enabled", True),
                target_tier=item.get("target_tier"),
                quantity=int(item.get("quantity", 250)),
                training_policy=str(item.get("training_policy", "once_daily")),
                allow_resource_boxes=item.get("allow_resource_boxes", False),
            )
        return TroopTrainingConfig(**values)
    return TroopTrainingConfig(
        fighter=TrainingConfig(target_tier=args.fighter_tier, quantity=args.fighter_quantity, training_policy=args.fighter_policy, allow_resource_boxes=args.fighter_allow_resource_boxes),
        shooter=TrainingConfig(target_tier=args.shooter_tier, quantity=args.shooter_quantity, training_policy=args.shooter_policy, allow_resource_boxes=args.shooter_allow_resource_boxes),
        rider=TrainingConfig(target_tier=args.rider_tier, quantity=args.rider_quantity, training_policy=args.rider_policy, allow_resource_boxes=args.rider_allow_resource_boxes),
        vehicle=TrainingConfig(target_tier=args.vehicle_tier, quantity=args.vehicle_quantity, training_policy=args.vehicle_policy, allow_resource_boxes=args.vehicle_allow_resource_boxes),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--reset-identity", required=True)
    parser.add_argument("--config", type=Path)
    for troop_type in TROOP_TYPES:
        parser.add_argument(f"--{troop_type}-tier", type=int)
        parser.add_argument(f"--{troop_type}-quantity", type=int, default=250)
        parser.add_argument(f"--{troop_type}-policy", choices=("once_daily", "continuous", "disabled"), default="once_daily")
        parser.add_argument(
            f"--{troop_type}-allow-resource-boxes",
            action=argparse.BooleanOptionalAction,
            default=False,
            help=f"allow exact Auto Use resource-box confirmation for {troop_type} only (default: false)",
        )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm the exact local BlueStacks target non-interactively")
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
        "--continue-from-radial",
        action="store_true",
        help="continue one positively recognized current radial into a single training view, then use tabs only",
    )
    parser.add_argument(
        "--continue-from-training",
        action="store_true",
        help="continue a positively recognized current training view using tabs only",
    )
    parser.add_argument("--training-troop-type", choices=TROOP_TYPES, default="shooter")
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
    if args.reconcile_resource_box_acquisition_session is not None:
        if not args.execute:
            result = TroopTrainingRecoveryResult(
                status="dry-run",
                reason="dry-run-no-input; resource-box acquisition recovery issued no input",
                actions_completed=0,
                recovered_action_key=None,
                troop_type=None,
                selected_tier=None,
                quantity=None,
                displayed_training_duration_seconds=None,
                expected_completion_timestamp=None,
                final_home_recognized=False,
                session=str(runtime.session),
            )
        else:
            result = TroopTrainingResourceBoxAcquisitionRecoveryRoute(
                runtime,
                previous_session=args.reconcile_resource_box_acquisition_session,
                post_input_delay=args.post_input_delay,
            ).run()
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0 if result.status in {"completed", "dry-run"} else 3
    if args.reconcile_forbidden_resource_popup_session is not None:
        if not args.execute:
            result = TroopTrainingRecoveryResult(
                status="dry-run",
                reason="dry-run-no-input; forbidden-popup recovery issued no input",
                actions_completed=0,
                recovered_action_key=None,
                troop_type=None,
                selected_tier=None,
                quantity=None,
                displayed_training_duration_seconds=None,
                expected_completion_timestamp=None,
                final_home_recognized=False,
                session=str(runtime.session),
            )
        else:
            result = TroopTrainingForbiddenPopupRecoveryRoute(
                runtime,
                previous_session=args.reconcile_forbidden_resource_popup_session,
                post_input_delay=args.post_input_delay,
            ).run()
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0 if result.status in {"completed", "dry-run"} else 3
    if args.reconcile_unresolved_session is not None:
        if not args.execute:
            result = TroopTrainingRecoveryResult(
                status="dry-run",
                reason="dry-run-no-input; recovery route issued no input",
                actions_completed=0,
                recovered_action_key=None,
                troop_type=None,
                selected_tier=None,
                quantity=None,
                displayed_training_duration_seconds=None,
                expected_completion_timestamp=None,
                final_home_recognized=False,
                session=str(runtime.session),
            )
        else:
            result = TroopTrainingUnresolvedRecoveryRoute(
                runtime,
                previous_session=args.reconcile_unresolved_session,
                post_input_delay=args.post_input_delay,
            ).run()
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0 if result.status in {"completed", "dry-run"} else 3
    if args.return_home_only:
        if not args.execute:
            result = TroopTrainingReturnHomeResult("dry-run", "dry-run-no-input; return-home route issued no input", 0, False, str(runtime.session))
        else:
            result = TroopTrainingReturnHomeRoute(runtime, post_input_delay=args.post_input_delay).run()
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0 if result.status in {"completed", "dry-run"} else 3
    config = _load_config(args)
    config.validate()
    if args.continue_from_radial:
        result = TroopTrainingIntegratedRoute(
            runtime,
            config=config,
            reset_identity=args.reset_identity,
            post_input_delay=args.post_input_delay,
        ).run_from_current_radial(args.radial_troop_type)
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0 if result.status in {"completed", "dry-run"} else 3
    if args.continue_from_training:
        result = TroopTrainingIntegratedRoute(
            runtime,
            config=config,
            reset_identity=args.reset_identity,
            post_input_delay=args.post_input_delay,
        ).run_from_current_training(args.training_troop_type)
        print(json.dumps(asdict(result), sort_keys=True, default=str))
        return 0 if result.status in {"completed", "dry-run"} else 3
    result = TroopTrainingIntegratedRoute(
        runtime,
        config=config,
        reset_identity=args.reset_identity,
        post_input_delay=args.post_input_delay,
    ).run()
    print(json.dumps(asdict(result), sort_keys=True, default=str))
    return 0 if result.status in {"completed", "dry-run"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
