#!/usr/bin/env python3
"""Native Campaign engine with standalone navigation and Victory recovery commands.

Dry-run is the default.  ``--execute`` is required for input, and every fresh frame plus command
is retained under ``.local-captures``.  This adapter never connects ADB and rejects non-local
BlueStacks serials. Ordinary AP execution uses ``pnsctl automation-service serve``;
the canonical service imports the route engine directly.

``--navigation-only`` verifies an exact supported Story destination and stops at
``destination_verified`` / ``navigation_only_complete`` without Challenge or AP consumption.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Callable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.bluestacks_flow_collector import is_permitted_local_bluestacks_serial
from scripts.bluestacks_native_runtime import CapturedNativeFrame, LocalBlueStacksRuntime
from scripts.home_atlas_bluestacks import (
    CAMPAIGN_HOME_ATLAS_BUILDING_ID,
    campaign_home_atlas_building_id,
    require_campaign_home_atlas_building,
    run_verified_campaign_home_atlas_entry,
)
from tasks.campaign_auto_battle import (
    BattleResult,
    CAMPAIGN_DRAIN_MAX_RUNS,
    CAMPAIGN_MAX_INPUTS,
    CampaignAction,
    CampaignAutoBattleConfig,
    CampaignRouteProgress,
    CampaignScreen,
    classify_battle_result,
    reconcile_observed_ap,
    parse_supported_campaign_story_destination,
)
from tasks.campaign_auto_battle_runtime import (
    CAMPAIGN_HOME_ATLAS_BUILDING_ID as RUNTIME_CAMPAIGN_BUILDING_ID,
    CampaignRuntimeController,
    CampaignRuntimeCommand,
)
from tasks.campaign_auto_battle_vision import CampaignFrameRecognition, recognize_campaign_frame
from tasks.campaign_ap_challenge import (
    CAMPAIGN_AP_FLOW_ID, CampaignApRouteResult, campaign_ap_challenge_policy_request,
    campaign_ap_effect_verified, campaign_ap_drain_verified,
)
from safe_action_core import ActionStatus, CentralPolicy, Observation, PolicyRequest, SafeActionExecutor, SafetyStore, TransportResult
from scripts.navigation_development_boundary import open_canonical_action_store


DEFAULT_HOME_ATLAS = (
    REPO_ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
)


@dataclass(frozen=True)
class CampaignStageEntryResult:
    status: str
    reason: str
    action_key: str
    transport_calls: int
    after_capture: CapturedNativeFrame | None = None
    after_recognition: CampaignFrameRecognition | None = None


class CampaignApRunError(RuntimeError):
    def __init__(self, reason: str, partial_result: dict[str, object]) -> None:
        super().__init__(reason)
        self.partial_result = partial_result


class CampaignStageChallengeBoundary:
    """One exact Stage entry per reconciled battle through the durable executor.

    CONFIRMED means Hero Lineup was observed. It does not commit an AP effect.
    The caller owns the canonical run/checkpoint and one-battle continuation.
    """

    def __init__(self, runtime, store: SafetyStore, config: CampaignAutoBattleConfig, *,
                 owner: str, game_day_id: str, monotonic_clock=time.monotonic,
                 utc_clock=time.time, sleep=time.sleep, settle_seconds: float = 1.0) -> None:
        self.runtime, self.store, self.config = runtime, store, config
        self.owner, self.game_day_id = owner, game_day_id
        self.monotonic_clock, self.utc_clock, self.sleep = monotonic_clock, utc_clock, sleep
        self.settle_seconds = settle_seconds
        self.attempted_entries = 0

    def __call__(self, source, recognition, command, *, progress: CampaignRouteProgress) -> CampaignStageEntryResult:
        from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID

        if (type(progress) is not CampaignRouteProgress
                or any(type(value) is not int or value < 0 for value in (
                    progress.initial_ap, progress.current_ap, progress.completed_runs,
                    progress.ap_spent, progress.ap_regenerated))
                or progress.initial_ap > 120 or progress.current_ap > 120
                or progress.completed_runs != self.attempted_entries
                or progress.completed_runs >= self.config.max_runs
                or progress.loss_seen is not False
                or progress.ap_spent != progress.completed_runs * self.config.ap_cost
                or progress.ap_spent + self.config.ap_cost > self.config.ap_budget
                or progress.current_ap != progress.initial_ap - progress.ap_spent + progress.ap_regenerated
                or type(recognition.observation.ap_current) is not int
                or progress.current_ap != recognition.observation.ap_current):
            raise RuntimeError("Campaign next entry requires the prior battle's verified Victory/AP ledger")
        self.attempted_entries += 1
        stage = self.config.target_stage
        expected_target = f"campaign-challenge-{stage.identity}"
        action_key = f"campaign-ap:{self.runtime.session.name}:entry:{self.attempted_entries}"

        def stage_observation(captured, found) -> Observation:
            facts = found.observation
            target = found.target(expected_target)
            if (command.action is not CampaignAction.CHALLENGE_STAGE
                    or facts.screen is not CampaignScreen.STAGE_DIALOG
                    or facts.stage_dialog != stage or not facts.challenge_ready
                    or facts.refill_visible or facts.ap_cost != self.config.ap_cost
                    or type(facts.ap_current) is not int or facts.ap_current < self.config.ap_cost
                    or target is None or target != command.target_roi
                    or found.frame_sha256 != hashlib.sha256(captured.frame.tobytes()).hexdigest()):
                raise ValueError("fresh Campaign Stage, cost, or target is not exact")
            height, width = captured.frame.shape[:2]
            return Observation(
                frame_sha256=captured.sha256,
                capture_completed_monotonic=captured.captured_monotonic,
                runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, width=width, height=height,
                valid_png=captured.frame.shape == (1280, 800, 3), corrupt=False,
                black=not bool(np.any(captured.frame)), source_state=facts.screen.value,
                overlay_state=facts.overlay_state, target_identity=expected_target, target_roi=target,
                recognized=facts.recognized, control_class="CHALLENGE", consequence="campaign_ap_auto_battle",
                cost_type="AP", cost_amount=facts.ap_cost, quantity=1,
                expected_postcondition="CAMPAIGN_HERO_LINEUP", target_isolated=True,
                package_foreground=self.runtime.measure_foreground_package() == "com.global.ztmslg",
                critical_roi_hashes=(("challenge", hashlib.sha256(captured.frame[target[1]:target[3], target[0]:target[2]].tobytes()).hexdigest()),),
                evidence_refs=(str(captured.path),),
                ocr_result_frame_sha256=captured.sha256,
                ocr_result_capture_completed_monotonic=captured.captured_monotonic,
            )

        # These are two genuine runtime captures. The supplied source is the
        # proposal; only the later capture can bind the one-shot capability.
        proposal = stage_observation(source, recognition)
        immediate_capture = self.runtime.capture("campaign-stage-policy-immediate-before")
        immediate_recognition = recognize_campaign_frame(immediate_capture.frame, stage)
        try:
            immediate = stage_observation(immediate_capture, immediate_recognition)
            if immediate_recognition.observation.ap_current != recognition.observation.ap_current:
                raise ValueError("Campaign AP balance changed before Stage entry")
            if immediate.capture_completed_monotonic <= proposal.capture_completed_monotonic:
                raise ValueError("Campaign immediate capture is not newer than the proposal")
        except ValueError as exc:
            return CampaignStageEntryResult("blocked", str(exc), action_key, 0)

        def request(observed):
            return campaign_ap_challenge_policy_request(
                PolicyRequest(
                    action_id=hashlib.sha256(action_key.encode()).hexdigest(), action_key=action_key,
                    task_id=CAMPAIGN_AP_FLOW_ID, task_mode="supervised_validation",
                    semantic_action="dispatch_campaign_ap_auto_battle",
                    expected_runtime_profile_id=observed.runtime_profile_id, observation=observed,
                    monotonic_now=self.monotonic_clock(), observation_max_age_seconds=30.0,
                    dispatch_max_age_seconds=30.0, lease_owner=self.owner,
                    lease_valid=self.store.lease_valid_for(self.owner, self.utc_clock()),
                    unresolved_action=self.store.has_action_block(),
                    duplicate_action_key=self.store.get_action_by_key(action_key) is not None,
                    game_day_id=self.game_day_id, runtime_session_id=str(self.runtime.session),
                ), stage_identity=stage.identity, current_ap=recognition.observation.ap_current,
                target_roi=observed.target_roi,
            )

        policy = CentralPolicy({CAMPAIGN_AP_FLOW_ID})
        immediate_request = request(immediate)
        issued = policy.issue_capability(immediate_request)
        self.store.audit(CAMPAIGN_AP_FLOW_ID, "capability_issued", self.utc_clock(), issued.audit,
                         immediate_request.action_id)
        if not issued.authorized or issued.capability is None:
            return CampaignStageEntryResult("blocked", issued.reason_code, action_key, 0)
        post = []
        immediate_returned = False

        def recapture():
            nonlocal immediate_returned
            if immediate_returned:
                raise ValueError("Campaign immediate capture cannot be reused for another attempt")
            immediate_returned = True
            return immediate

        def transport(_intent):
            self.runtime.tap(immediate_capture, target_identity=expected_target,
                             target_roi=immediate.target_roi, action_key=action_key,
                             action_class="campaign_ap_challenge", consequential=True)
            return TransportResult(True, "BLUESTACKS_TAP_DISPATCHED")

        def post_observe():
            for ordinal in range(1, 4):
                self.sleep(self.settle_seconds)
                captured = self.runtime.capture(f"campaign-stage-entry-post-{ordinal}")
                found = recognize_campaign_frame(captured.frame, stage)
                post.append((captured, found))
                facts = found.observation
                target = found.target("campaign-lineup-challenge")
                positive = (facts.screen is CampaignScreen.HERO_LINEUP and facts.recognized
                            and facts.lineup_challenge_ready and target is not None)
                height, width = captured.frame.shape[:2]
                # A Lineup observation contains its own visible facts. It says
                # nothing about AP expenditure or the Stage's displayed price.
                yield Observation(
                    frame_sha256=captured.sha256, capture_completed_monotonic=captured.captured_monotonic,
                    runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID, width=width, height=height,
                    valid_png=captured.frame.shape == (1280, 800, 3), corrupt=False,
                    black=not bool(np.any(captured.frame)), source_state=facts.screen.value,
                    overlay_state=facts.overlay_state, recognized=facts.recognized,
                    target_identity="campaign-lineup-challenge" if positive else None,
                    target_roi=target if positive else None, target_isolated=positive,
                    evidence_refs=(str(captured.path),),
                )
                if positive:
                    return

        execution = SafeActionExecutor(
            self.store, policy, self.owner, self.monotonic_clock, transport, recapture,
            post_observe, lambda _intent, observed: (
                observed.recognized and observed.source_state == CampaignScreen.HERO_LINEUP.value
                and observed.target_identity == "campaign-lineup-challenge" and observed.target_isolated),
            wall_clock=self.utc_clock, max_pre_dispatch_attempts=1,
        ).execute(request(proposal), issued.capability)
        positive = next(((captured, found) for captured, found in post
                         if found.observation.screen is CampaignScreen.HERO_LINEUP
                         and found.observation.recognized and found.observation.lineup_challenge_ready
                         and found.target("campaign-lineup-challenge") is not None), None)
        if execution.status is ActionStatus.CONFIRMED and positive is not None:
            self.runtime.reconcile(action_key, "confirmed", positive[0], "Stage entry verified Hero Lineup only; AP effect pending")
            return CampaignStageEntryResult("confirmed", execution.reason, action_key,
                                            execution.transport_calls, *positive)
        return CampaignStageEntryResult("unresolved" if execution.transport_calls else "blocked",
                                        execution.reason, action_key, execution.transport_calls)


def _victory_home_command_allowed(command: CampaignRuntimeCommand) -> bool:
    if command.kind == "wait":
        return command.action is CampaignAction.WAIT_FOR_BATTLE_RESULT
    if command.kind == "terminal":
        return command.action in {CampaignAction.COMPLETE, CampaignAction.BLOCKED}
    targets = {
        CampaignAction.CONTINUE_VICTORY: {"campaign-victory-continue"},
        CampaignAction.LEAVE_CHAPTER_MAP: {"campaign-chapter-back"},
        CampaignAction.RETURN_HOME: {"campaign-exit-base", "campaign-base-request"},
        CampaignAction.CLOSE_STAGE_DIALOG: {"campaign-stage-dialog-close"},
    }
    return command.kind == "tap" and command.target_identity in targets.get(command.action, set())


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def append_event(path: Path, event: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def write_navigation_only_evidence(session: Path, result: dict[str, object]) -> None:
    """Persist navigation-only ledger/journal/capability-audit required by flow-delivery evidence."""

    status = str(result.get("status") or "unknown")
    reason = str(result.get("reason") or "")
    navigation_only = bool(result.get("navigation_only", True))
    progress = result.get("progress")
    if hasattr(progress, "__dict__"):
        progress = dict(progress.__dict__)
    row = {
        "status": status,
        "reason": reason,
        "navigation_only": navigation_only,
        "session": str(session),
        "destination": result.get("destination"),
        "ap_before": result.get("ap_before"),
        "ap_after": result.get("ap_after"),
        "ap_cost": result.get("ap_cost"),
        "battle_outcome": result.get("battle_outcome"),
        "progress": progress,
        **({"victory_home_only": True, "new_battle_count": 0} if result.get("victory_home_only") else {}),
    }
    for name in ("ledger.jsonl", "journal.jsonl", "capability-audit.jsonl"):
        path = session / name
        if path.exists() and path.stat().st_size > 0:
            continue
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            if name == "capability-audit.jsonl":
                handle.write(
                    json.dumps(
                        {
                            **row,
                            "authority": "CampaignRuntimeController",
                            "authorized": status
                            in {"destination_verified", "navigation_only_complete", "completed"},
                            "transport_observed": status == "completed" and not navigation_only,
                            "consequence_class": "navigation_only" if navigation_only else "campaign_ap_auto_battle",
                        },
                        sort_keys=True,
                        default=str,
                    )
                    + "\n"
                )
            else:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def relocalization_residual_pixels(
    localization_residual_px: float | None,
    remaining_displacement: tuple[float, float] | None = None,
) -> float | None:
    """Prefer Home Atlas localization residual; else pan remaining displacement magnitude."""

    if localization_residual_px is not None:
        return float(localization_residual_px)
    if remaining_displacement is None:
        return None
    return float(math.hypot(remaining_displacement[0], remaining_displacement[1]))


_CAMPAIGN_ENTRY_OPEN_SCREENS = frozenset(
    {
        CampaignScreen.TIER_MAP,
        CampaignScreen.CHAPTER_MAP,
        CampaignScreen.STAGE_DIALOG,
        CampaignScreen.HERO_LINEUP,
    }
)


def _campaign_entry_semantically_opened(frame: np.ndarray) -> bool:
    """True only when post-entry vision binds Campaign/TIER_MAP (or equivalent)."""

    # Screen classification only; any supported destination supplies OCR targets.
    stage = parse_supported_campaign_story_destination("1-20-9")
    recognition = recognize_campaign_frame(frame, stage)
    return (
        recognition.observation.recognized
        and recognition.observation.screen in _CAMPAIGN_ENTRY_OPEN_SCREENS
    )


def _dispatch_home_atlas_campaign_entry(
    *,
    runtime,
    events: Path,
    maximum_pans: int = 4,
    post_input_delay: float = 1.0,
    atlas_path: Path = DEFAULT_HOME_ATLAS,
) -> dict[str, object]:
    """Pan/bind/open Campaign via verified Home Atlas path; never raw ADB or HOME_PAN_GESTURES."""

    building_id = require_campaign_home_atlas_building(atlas_path)
    assert building_id == RUNTIME_CAMPAIGN_BUILDING_ID == campaign_home_atlas_building_id()
    before = runtime.input_count
    result = {
        **run_verified_campaign_home_atlas_entry(
            runtime,
            atlas_path=atlas_path,
            maximum_pans=maximum_pans,
            execute=True,
            settle_seconds=post_input_delay,
            semantic_opened_check=_campaign_entry_semantically_opened,
        ),
        "navigation_input_count": runtime.input_count - before,
    }
    append_event(
        events,
        {
            "type": "home_atlas_entry_verified",
            "building_id": building_id,
            "entry_session": str(runtime.session),
            **{k: v for k, v in result.items() if k != "tap_telemetry"},
        },
    )
    return result


def _revalidate_campaign_navigation(runtime, source, recognition, command, stage, *, observe):
    """Refresh a planned map input without running the stateful atlas planner twice.

    Atlas search can outlive a dispatch source. A later recognized map and a
    measured near-identity viewport preserve that plan; neither an old target
    nor a registration alone authorizes a tap.
    """
    from tasks.campaign_atlas_vision import (
        OrbTranslationBackend, campaign_hud_mask, loop_closure_accepted,
        native_campaign_frame_guard,
    )

    expected_screen = {
        CampaignAction.NAVIGATE_CHAPTER: CampaignScreen.TIER_MAP,
        CampaignAction.NAVIGATE_STAGE: CampaignScreen.CHAPTER_MAP,
    }.get(command.action)
    if expected_screen is None or command.kind not in {"tap", "swipe"}:
        raise RuntimeError("Campaign navigation refresh requires a planned map input")
    immediate = runtime.capture("campaign-navigation-immediate-before")
    if (not native_campaign_frame_guard(source.frame)
            or not native_campaign_frame_guard(immediate.frame)
            or immediate.path == source.path
            or immediate.captured_monotonic <= source.captured_monotonic):
        raise RuntimeError("Campaign navigation refresh lacks a later native capture")
    fresh = observe(immediate)
    for captured, found in ((source, recognition), (immediate, fresh)):
        if found.frame_sha256 != hashlib.sha256(captured.frame.tobytes()).hexdigest():
            raise RuntimeError("Campaign navigation recognition does not match its actual capture")
        observed = found.observation
        if (not observed.recognized or observed.screen is not expected_screen
                or observed.overlay_state not in {"none", "none_observed"}
                or observed.selected_tier != stage.tier or observed.refill_visible
                or (expected_screen is CampaignScreen.TIER_MAP
                    and not observed.chapter_navigation_available)
                or (expected_screen is CampaignScreen.CHAPTER_MAP
                    and (observed.chapter_number != stage.chapter or not observed.stage_navigation_available))):
            raise RuntimeError("Campaign navigation context changed before dispatch")
    before_ap, current_ap = recognition.observation.ap_current, fresh.observation.ap_current
    if (before_ap is not None and (type(current_ap) is not int or current_ap < before_ap)):
        raise RuntimeError("Campaign navigation AP balance changed unexpectedly before dispatch")
    measurement = OrbTranslationBackend().measure(immediate.frame, source.frame, campaign_hud_mask())
    if not loop_closure_accepted(measurement):
        raise RuntimeError("Campaign navigation viewport changed or could not be measured before dispatch")
    rebound = command
    if command.kind == "tap":
        identity = command.target_identity
        if not identity or command.target_roi is None:
            raise RuntimeError("Campaign navigation tap lacks an exact target identity")
        target = fresh.target(identity)
        if command.action is CampaignAction.NAVIGATE_CHAPTER:
            from tasks.campaign_atlas_chapter_nav import (
                chapter_roi_is_safely_framed, ocr_chapter_roi_near_projection,
            )

            if identity != f"campaign-chapter-{stage.chapter}":
                raise RuntimeError("Campaign navigation chapter identity changed before dispatch")
            if target is None:
                x0, y0, x1, y1 = command.target_roi
                target = ocr_chapter_roi_near_projection(
                    immediate.frame, chapter=stage.chapter,
                    projected_screen_center=((x0 + x1) / 2.0, (y0 + y1) / 2.0),
                )
            if target is not None and not chapter_roi_is_safely_framed(target):
                target = None
        elif identity != f"campaign-stage-{stage.identity}":
            raise RuntimeError("Campaign navigation stage identity changed before dispatch")
        if target is None:
            raise RuntimeError("Campaign navigation target was not rebound in the fresh capture")
        previous = command.target_roi
        if (max(previous[0], target[0]) >= min(previous[2], target[2])
                or max(previous[1], target[1]) >= min(previous[3], target[3])):
            raise RuntimeError("Campaign navigation target moved outside its measured source control")
        rebound = replace(command, target_roi=target)
    elif command.swipe is None:
        raise RuntimeError("Campaign navigation pan lacks its planned gesture")
    append_event(runtime.events, {
        "type": "navigation_revalidation", "action": command.action.value,
        "proposal_frame": str(source.path), "proposal_sha256": source.sha256,
        "proposal_captured_monotonic": source.captured_monotonic,
        "immediate_frame": str(immediate.path), "immediate_sha256": immediate.sha256,
        "immediate_captured_monotonic": immediate.captured_monotonic,
        "translation_px": measurement.translation_px, "residual_px": measurement.residual_px,
        "matches": measurement.matches, "target_identity": rebound.target_identity,
        "target_roi": rebound.target_roi, "swipe": rebound.swipe,
    })
    return immediate, fresh, rebound


def run_campaign_ap_route(
    runtime, config: CampaignAutoBattleConfig, *, checkpoint: Callable[[], None],
    stage_challenge_boundary=None, atlas_path: Path = DEFAULT_HOME_ATLAS,
    terminal_home_ap_reader: Callable[[CapturedNativeFrame], int] | None = None,
    terminal_home_normalizer: Callable[[CapturedNativeFrame], CapturedNativeFrame] | None = None,
    maximum_steps: int = 1000, recognition_timeout: float = 25.0,
    post_input_delay: float = 1.0, initial_ap: int | None = None,
    victory_home_only: bool = False, monotonic_clock=time.monotonic, sleep=time.sleep,
) -> dict[str, object]:
    """Run the single native controller loop under the caller's existing owner.

    The supplied checkpoint fences every capture and input, including Home Atlas
    and policy execution. Entry confirmation grants one Lineup continuation; only
    each Victory/AP debit is retained. Whole-route completion requires a fresh
    drained Home; each new entry keeps its own one-shot Lineup continuation.
    """
    if not callable(checkpoint):
        raise ValueError("Campaign requires a current execution checkpoint")
    if not 1 <= runtime.max_inputs <= CAMPAIGN_MAX_INPUTS:
        raise ValueError("Campaign native input limit is outside its bounded contract")
    if not config.navigation_only and (type(config.max_runs) is not int or not 1 <= config.max_runs <= CAMPAIGN_DRAIN_MAX_RUNS
            or type(config.ap_budget) is not int or config.ap_budget > config.ap_cost * CAMPAIGN_DRAIN_MAX_RUNS):
        raise ValueError("Campaign AP drain exceeds its run or AP backstop")
    if victory_home_only and (config.navigation_only or type(initial_ap) is not int or initial_ap < config.ap_cost):
        raise ValueError("Victory recovery requires a verified initial AP balance")
    if initial_ap is not None and not victory_home_only:
        raise ValueError("initial_ap is reserved for validated Victory recovery")
    if (not 1 <= maximum_steps <= 1000
            or not all(math.isfinite(value) for value in (recognition_timeout, post_input_delay,
                                                         config.battle_timeout_seconds, config.battle_poll_seconds))
            or recognition_timeout <= 0 or post_input_delay < 0):
        raise ValueError("Campaign observation bounds are invalid")
    runtime.checkpoint = checkpoint
    session = Path(runtime.session)
    # Keep native transport records separate from the historical semantic step
    # stream. Existing evidence readers can still replay their exact old format.
    if runtime.events == session / "events.jsonl" and not runtime.events.exists():
        runtime.events = session / "native-events.jsonl"
    events = session / ("campaign-events.jsonl" if runtime.events == session / "events.jsonl" else "events.jsonl")
    controller = CampaignRuntimeController(replace(config, victory_home_only=True) if victory_home_only else config,
                                           initial_ap=initial_ap)
    stage = config.target_stage
    started = monotonic_clock()
    battle_started = None
    victory_successor_deadline = None
    last_recognition = None
    source = None
    cached = None
    entry = None
    entry_attempted = False
    entry_inputs = 0
    entry_action_keys = []
    new_battles = 0
    confirmed_effects = 0
    lineup_attempted = False
    lineage_key = None
    first_source = True
    result_successor_verified = False
    last_relocalization_residual_pixels = None
    terminal_home_capture = None

    def observe(captured, step):
        elapsed = 0 if battle_started is None else monotonic_clock() - battle_started
        found = recognize_campaign_frame(captured.frame, stage, battle_elapsed_seconds=elapsed)
        append_event(events, {
            "type": "observation", "step": step, "frame": str(captured.path),
            "frame_sha256": found.frame_sha256, "screen": found.observation.screen.value,
            "recognized": found.observation.recognized, "targets": dict(found.targets),
            "diagnostics": found.diagnostics,
        })
        return found

    def finish(status, reason):
        progress = controller.progress
        home = bool(last_recognition and last_recognition.observation.recognized
                    and last_recognition.observation.screen is CampaignScreen.HOME_BASE)
        effect = bool(progress and (
            (victory_home_only and progress.completed_runs == 1 and result_successor_verified and home
             and campaign_ap_effect_verified(CampaignApRouteResult(
                 stage.identity, progress.initial_ap, progress.current_ap, progress.ap_regenerated,
                 "victory", "CAMPAIGN_CHAPTER_MAP", "HOME_BASE", 1, False)))
            or (not victory_home_only and confirmed_effects == progress.completed_runs == new_battles == entry_inputs
                and len(entry_action_keys) == entry_inputs and len(set(entry_action_keys)) == entry_inputs
                and campaign_ap_drain_verified(stage.identity, progress, battle_outcome="victory",
                    result_successor_verified=result_successor_verified, terminal_home_verified=home))))
        if status == "completed" and not effect:
            status, reason = "blocked_fail_closed", "Campaign AP drain lacks verified Victory/AP effects, drained balance, or Home"
        result = {
            "status": status, "terminal": "navigation_only_complete" if status in {
                "destination_verified", "navigation_only_complete"} else status,
            "reason": reason, "session": str(session), "navigation_only": config.navigation_only,
            "progress": progress.__dict__ if progress else None, "destination": stage.identity,
            "ap_before": progress.initial_ap if progress else None,
            "ap_after": progress.current_ap if progress else None, "ap_cost": config.ap_cost,
            "battle_outcome": "victory" if progress and progress.completed_runs else "defeat" if progress and progress.loss_seen else None,
            "navigation_input_count": runtime.input_count, "input_count": runtime.input_count,
            "total_input_count": runtime.input_count, "new_battle_count": new_battles,
            "stage_entry_transport_count": entry_inputs,
            "entry_action_key": entry.action_key if isinstance(entry, CampaignStageEntryResult) else None,
            "entry_action_keys": list(entry_action_keys),
            "committed_ap_effect_count": confirmed_effects, "terminal_home_verified": home,
            "terminal_home_frame": str(terminal_home_capture.path) if terminal_home_capture is not None else None,
            "terminal_home_sha256": terminal_home_capture.sha256 if terminal_home_capture is not None else None,
            "result_successor_verified": result_successor_verified,
            "effect_reconciliation_required": bool(not effect and (new_battles or entry_inputs)),
            "relocalization_residual_pixels": last_relocalization_residual_pixels,
            "destination_verification_latency_seconds": monotonic_clock() - started,
            "native_events_path": str(runtime.events), "step_events_path": str(events),
            **({"victory_home_only": True} if victory_home_only else {}),
        }
        (session / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_navigation_only_evidence(session, result)
        return result

    try:
        checkpoint()
        for step in range(1, maximum_steps + 1):
            deadline = (battle_started + config.battle_timeout_seconds if battle_started is not None
                        else monotonic_clock() + recognition_timeout)
            if victory_successor_deadline is not None:
                deadline = min(deadline, victory_successor_deadline)
            recognition = None
            while monotonic_clock() < deadline:
                if cached is None:
                    source = runtime.capture(f"campaign-route-{step:03d}")
                    candidate = observe(source, step)
                else:
                    source, candidate = cached
                    cached = None
                    # The accepted entry successor is retained in the step stream.
                    candidate = observe(source, step)
                if candidate.observation.recognized:
                    recognition = candidate
                    break
                sleep(min(0.5, config.battle_poll_seconds))
            if recognition is None:
                if victory_successor_deadline is not None:
                    return finish("blocked_fail_closed", "Victory Continue successor timed out")
                raise RuntimeError("no recognized Campaign state before recognition timeout")
            last_recognition = recognition
            screen = recognition.observation.screen
            if (screen is CampaignScreen.BATTLE and battle_started is None
                    and not (victory_home_only and first_source)):
                battle_started = monotonic_clock()
            elif screen is not CampaignScreen.BATTLE:
                battle_started = None
            if victory_home_only and first_source and classify_battle_result(recognition.observation) is not BattleResult.VICTORY:
                return finish("blocked_fail_closed", "victory-home recovery requires a recognized Victory source")
            if not victory_home_only and first_source and screen in {CampaignScreen.HERO_LINEUP, CampaignScreen.BATTLE, CampaignScreen.RESULT}:
                return finish("blocked_fail_closed", "fresh Campaign run cannot adopt an unrelated battle or Lineup")
            if (not victory_home_only and screen in {CampaignScreen.BATTLE, CampaignScreen.RESULT}
                    and (not lineup_attempted or lineage_key is None
                         or new_battles != confirmed_effects + 1)):
                return finish("blocked_fail_closed", "Campaign battle or result lacks this run's Lineup continuation")
            first_source = False
            if victory_successor_deadline is not None and monotonic_clock() >= victory_successor_deadline:
                return finish("blocked_fail_closed", "Victory Continue successor timed out")
            command = controller.next_command(recognition, frame=source.frame)
            if controller.progress and controller.progress.completed_runs > confirmed_effects:
                if (controller.progress.completed_runs != confirmed_effects + 1
                        or (not victory_home_only and (not lineup_attempted or lineage_key is None
                            or new_battles != controller.progress.completed_runs
                            or entry_inputs != controller.progress.completed_runs))):
                    return finish("blocked_fail_closed", "Campaign Victory/AP proof does not match the active battle")
                confirmed_effects = controller.progress.completed_runs
                entry_attempted = lineup_attempted = False
                lineage_key = None
                victory_successor_deadline = None
                result_successor_verified = True
            if (command.action is CampaignAction.COMPLETE and screen is CampaignScreen.HOME_BASE
                    and not config.navigation_only):
                terminal = runtime.capture("campaign-route-terminal-home")
                if terminal_home_normalizer is not None:
                    terminal = terminal_home_normalizer(terminal)
                if terminal_home_ap_reader is not None:
                    observed_ap = terminal_home_ap_reader(terminal)
                else:
                    found = observe(terminal, step)
                    if (not found.observation.recognized or found.observation.screen is not CampaignScreen.HOME_BASE
                            or found.observation.overlay_state not in {"none", "none_observed"}):
                        raise ValueError("Campaign terminal Home is not positively recognized")
                    observed_ap = found.observation.ap_current
                if type(observed_ap) is not int or not 0 <= observed_ap <= 120:
                    raise ValueError("Campaign terminal Home AP is not an exact balance")
                controller.progress = reconcile_observed_ap(controller.progress, ap_observed=observed_ap)
                append_event(events, {"type": "terminal_home_ap", "frame": str(terminal.path),
                    "frame_sha256": terminal.sha256, "captured_monotonic": terminal.captured_monotonic,
                    "ap_observed": observed_ap, "progress": controller.progress.__dict__})
                terminal_home_capture = terminal
                if not victory_home_only and observed_ap >= config.ap_cost:
                    if (controller.progress.completed_runs >= config.max_runs
                            or controller.progress.ap_spent + config.ap_cost > config.ap_budget):
                        return finish("blocked_fail_closed", "Campaign backstop reached before available AP was drained")
                    terminal_home_capture = None
                    checkpoint()
                    continue
            if command.action is CampaignAction.CHALLENGE_STAGE:
                if entry_attempted or not callable(stage_challenge_boundary):
                    return finish("blocked_fail_closed", "Campaign Stage entry requires one accepted policy boundary")
                source = runtime.capture("campaign-stage-challenge-immediate-before")
                recognition = observe(source, step)
                last_recognition = recognition
                command = controller.next_command(recognition, frame=source.frame)
                if command.action is not CampaignAction.CHALLENGE_STAGE:
                    return finish("blocked_fail_closed", "fresh Campaign Stage or AP cost changed before policy entry")
            if victory_home_only and not _victory_home_command_allowed(command):
                return finish("blocked_fail_closed", "victory-home recovery forbids new battle or entry actions")
            if (not command.terminal and command.kind in {"tap", "swipe"}
                    and command.action in {CampaignAction.NAVIGATE_CHAPTER, CampaignAction.NAVIGATE_STAGE}):
                source, recognition, command = _revalidate_campaign_navigation(
                    runtime, source, recognition, command, stage,
                    observe=lambda captured: observe(captured, step),
                )
                last_recognition = recognition
            append_event(events, {
                "type": "command", "step": step, "action": command.action.value, "kind": command.kind,
                "reason": command.reason, "target_identity": command.target_identity,
                "target_roi": command.target_roi, "tap_point": command.tap_point, "swipe": command.swipe,
                "progress": controller.progress.__dict__ if controller.progress else None,
            })
            if command.terminal:
                status = {CampaignAction.COMPLETE: "completed", CampaignAction.DESTINATION_VERIFIED: "destination_verified",
                          CampaignAction.NAVIGATION_ONLY_COMPLETE: "navigation_only_complete"}.get(command.action, "blocked_fail_closed")
                return finish(status, command.reason)
            if command.kind == "wait":
                sleep(command.wait_seconds or config.battle_poll_seconds)
                continue
            if command.kind == "home_atlas_entry":
                opened = _dispatch_home_atlas_campaign_entry(runtime=runtime, events=events,
                    post_input_delay=post_input_delay, atlas_path=atlas_path)
                append_event(events, {"type": "home_atlas_entry_result", **opened})
                last_relocalization_residual_pixels = opened.get("relocalization_residual_pixels")
                if opened.get("status") != "opened":
                    return finish("blocked_fail_closed", str(opened.get("reason") or "Home Atlas Campaign entry failed"))
                controller.accept_dispatched(command)
                continue
            if command.action is CampaignAction.CHALLENGE_STAGE:
                before = runtime.input_count
                entry_attempted = True
                try:
                    entry = stage_challenge_boundary(source, recognition, command, progress=controller.progress)
                finally:
                    entry_inputs += runtime.input_count - before
                if (runtime.input_count - before == 1 and isinstance(entry, CampaignStageEntryResult)
                        and type(entry.action_key) is str and entry.action_key):
                    entry_action_keys.append(entry.action_key)
                if (not isinstance(entry, CampaignStageEntryResult) or entry.status != "confirmed"
                        or entry.transport_calls != 1 or runtime.input_count - before != 1
                        or entry.after_capture is None or entry.after_recognition is None
                        or entry.after_recognition.observation.screen is not CampaignScreen.HERO_LINEUP
                        or not entry.after_recognition.observation.lineup_challenge_ready
                        or entry.after_recognition.target("campaign-lineup-challenge") is None):
                    return finish("blocked_fail_closed", "Campaign Stage entry was not confirmed by Hero Lineup")
                lineage_key = entry.action_key
                cached = (entry.after_capture, entry.after_recognition)
            elif command.kind == "tap":
                if command.action is CampaignAction.CONFIRM_LINEUP:
                    if lineup_attempted or lineage_key is None or entry is None:
                        return finish("blocked_fail_closed", "Lineup requires the same run's single confirmed Stage entry")
                    lineup_attempted = True
                before = runtime.input_count
                try:
                    runtime.tap(source, target_identity=command.target_identity, target_roi=command.target_roi,
                                action_key=f"campaign:{session.name}:{step}:{command.action.value}",
                                consequential=command.action is CampaignAction.CONFIRM_LINEUP,
                                continuation_of=lineage_key if command.action in {
                                    CampaignAction.CONFIRM_LINEUP, CampaignAction.ENABLE_AUTO,
                                    CampaignAction.CONTINUE_VICTORY} else None)
                finally:
                    if command.action is CampaignAction.CONFIRM_LINEUP:
                        # A reserved/ambiguous transport remains a possible battle;
                        # a pre-transport budget/checkpoint rejection does not.
                        new_battles += int(runtime.input_count > before)
            elif command.kind == "swipe":
                x0, y0, x1, y1, duration = command.swipe
                runtime.swipe(source, start=(x0, y0), end=(x1, y1), duration_ms=duration,
                              action_key=f"campaign:{session.name}:{step}:{command.action.value}",
                              target_identity=command.target_identity or "campaign-map-pan")
            else:
                raise RuntimeError(f"unsupported Campaign command kind: {command.kind}")
            controller.accept_dispatched(command)
            if command.action is CampaignAction.CONTINUE_VICTORY:
                victory_successor_deadline = monotonic_clock() + recognition_timeout
            sleep(post_input_delay)
        raise RuntimeError("Campaign AP maximum controller steps exceeded")
    except BaseException as exc:
        partial = finish("blocked_fail_closed", f"{type(exc).__name__}: {exc}")
        raise CampaignApRunError(str(exc), partial) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, help="BlueStacks HD-Adb.exe path")
    parser.add_argument("--serial", required=True, help="exact local BlueStacks serial")
    parser.add_argument(
        "--stage",
        required=True,
        help="supported Story destination difficulty-chapter-stage, for example 1-20-9",
    )
    parser.add_argument("--ap-cost", required=True, type=int)
    parser.add_argument("--ap-budget", required=True, type=int)
    parser.add_argument("--max-runs", required=True, type=int)
    parser.add_argument("--max-inputs", type=int, default=CAMPAIGN_MAX_INPUTS)
    parser.add_argument("--initial-ap", type=int, help="resume-only verified AP before an in-flight battle")
    parser.add_argument("--victory-home-only", action="store_true",
                        help="reconcile one already-won battle and return Home without starting a battle")
    parser.add_argument("--battle-timeout", type=float, default=180)
    parser.add_argument("--poll-seconds", type=float, default=1)
    parser.add_argument("--post-input-delay", type=float, default=1)
    parser.add_argument("--recognition-timeout", type=float, default=25)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument(
        "--navigation-only",
        action="store_true",
        help="verify destination only; stop before Challenge/AP",
    )
    parser.add_argument("--atlas", type=Path, default=DEFAULT_HOME_ATLAS)
    parser.add_argument("--execute", action="store_true", help="allow navigation or Victory recovery dispatch")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive serial confirmation (required for operator-driven live delivery)",
    )
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/campaign-ap-live"))
    args = parser.parse_args(argv)
    if args.execute and not args.navigation_only and not args.victory_home_only:
        parser.error(
            "ordinary Campaign AP execution uses pnsctl automation-service serve; "
            "standalone execution supports --navigation-only or verified --victory-home-only recovery"
        )
    if not 1 <= args.max_inputs <= CAMPAIGN_MAX_INPUTS:
        parser.error(f"--max-inputs must be between 1 and {CAMPAIGN_MAX_INPUTS}")

    if not is_permitted_local_bluestacks_serial(args.serial):
        parser.error("serial is not a permitted local BlueStacks endpoint")
    stage = parse_supported_campaign_story_destination(args.stage)
    require_campaign_home_atlas_building(args.atlas)
    config = CampaignAutoBattleConfig(
        target_stage=stage,
        ap_cost=args.ap_cost,
        ap_budget=args.ap_budget,
        max_runs=args.max_runs,
        battle_poll_seconds=args.poll_seconds,
        battle_timeout_seconds=args.battle_timeout,
        navigation_only=bool(args.navigation_only),
    )
    if not config.navigation_only and (config.max_runs > CAMPAIGN_DRAIN_MAX_RUNS
            or config.ap_budget > config.ap_cost * CAMPAIGN_DRAIN_MAX_RUNS):
        parser.error("native AP drain exceeds the run or AP backstop")
    if args.initial_ap is not None and not args.victory_home_only:
        parser.error("--initial-ap requires validated --victory-home-only recovery")
    if args.victory_home_only and (
        config.navigation_only or config.max_runs != 1 or config.ap_budget != config.ap_cost
        or args.initial_ap is None or args.initial_ap < config.ap_cost
    ):
        parser.error("--victory-home-only requires non-navigation mode, --max-runs 1, "
                     "--ap-budget equal to --ap-cost, and verified --initial-ap at least the cost")
    recovery_fields = {"victory_home_only": True, "new_battle_count": 0} if args.victory_home_only else {}
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "dry-run",
                    "stage": stage.identity,
                    "dispatch": False,
                    "navigation_only": config.navigation_only,
                    "campaign_home_atlas_building_id": CAMPAIGN_HOME_ATLAS_BUILDING_ID,
                    **recovery_fields,
                },
                sort_keys=True,
            )
        )
        return 0

    mode = "navigation-only" if config.navigation_only else "AP"
    if not args.yes:
        answer = input(
            f"Confirm exact BlueStacks serial '{args.serial}' for Campaign {mode} {stage.identity}? [y/N]: "
        )
        if answer.strip().casefold() not in {"y", "yes"}:
            print("Campaign AP run cancelled", file=sys.stderr)
            return 2

    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb, serial=args.serial, output_directory=args.output_directory,
        workflow=stage.identity, execute=True,
    )
    runtime.max_inputs = min(runtime.max_inputs, args.max_inputs)
    owner = f"campaign-ap:{runtime.session.name}"
    game_day = f"game-day-{datetime.now(timezone.utc).date().isoformat()}"
    store = open_canonical_action_store()
    leased = False
    try:
        store.acquire_lease(owner, time.time(), 3600.0)
        leased = True

        def checkpoint():
            if not store.lease_valid_for(owner, time.time()):
                raise RuntimeError("Campaign action lease lost")
            if game_day != f"game-day-{datetime.now(timezone.utc).date().isoformat()}":
                raise RuntimeError("Campaign game-day changed during execution")

        try:
            result = run_campaign_ap_route(
                runtime, config, checkpoint=checkpoint, stage_challenge_boundary=None,
                atlas_path=args.atlas, maximum_steps=args.max_steps,
                recognition_timeout=args.recognition_timeout, post_input_delay=args.post_input_delay,
                initial_ap=args.initial_ap, victory_home_only=args.victory_home_only,
                monotonic_clock=time.monotonic, sleep=time.sleep,
            )
        except CampaignApRunError as exc:
            result = exc.partial_result
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in {"completed", "destination_verified", "navigation_only_complete"} else 3
    finally:
        try:
            if leased:
                store.release_lease(owner, time.time())
        finally:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
