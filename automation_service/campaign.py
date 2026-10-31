"""Campaign navigation selector and separately bound native AP execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping

from tasks.campaign_atlas import (
    NAVIGATION_BLOCKED_FAIL_CLOSED,
    NAVIGATION_EVIDENCE_REQUIRED,
    ZERO_TRANSPORT_REPLAY_COMPLETE,
    plan_shared_campaign_destination_navigation,
)
from tasks.campaign_auto_battle import parse_supported_campaign_story_destination
from tasks.campaign_auto_battle import (
    CAMPAIGN_DRAIN_MAX_RUNS, CAMPAIGN_MAX_INPUTS, CampaignAutoBattleConfig, CampaignRouteProgress, CampaignScreen,
    reconcile_observed_ap,
)
from tasks.campaign_auto_battle_vision import recognize_campaign_frame
from tasks.campaign_ap_challenge import (
    CAMPAIGN_AP_COSTS, CAMPAIGN_AP_FLOW_ID, campaign_ap_drain_verified,
)
from tasks.scheduler_task_result import SchedulerIdentity
from .handlers import CampaignApSelectionHandler
from .registry import CAMPAIGN_PROFILE_ID

from .contracts import (
    FlowDescriptor,
    NormalizedOutcome,
    NormalizedResult,
    PerceptionEnvelope,
    SchedulerFacts,
    SemanticActionIntent,
    RecurrenceClass,
    RecurrenceProjection,
)


CAMPAIGN_FLOW_ID = "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION"
FORBIDDEN_CAMPAIGN_INPUTS = frozenset({"sweep", "blitz", "auto_complete", "ap_refill"})
FORBIDDEN_NAVIGATION_ACTIONS = frozenset(
    {"ap", "challenge", "auto_battle", *FORBIDDEN_CAMPAIGN_INPUTS}
)


@dataclass(frozen=True)
class CampaignNavigationPlan:
    destination: str
    decision: Any
    navigation_only: bool = True


class CampaignNavigationHandler:
    """Navigation-only Campaign handler; AP and battle transitions are not exposed."""

    def __init__(self, destination: str = "1-20-9") -> None:
        stage = parse_supported_campaign_story_destination(destination)
        self.destination = stage.identity

    def describe(self) -> FlowDescriptor:
        return FlowDescriptor(
            flow_id=CAMPAIGN_FLOW_ID,
            owner="automation_service",
            family="campaign",
            variant="navigation_only",
            cadence="evidence_gated",
            priority=25,
            scheduler_eligible=False,
        )

    def eligibility(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> bool:
        if not facts.health_ok or facts.unresolved_action or facts.breakers:
            return False
        if perception is None:
            return True
        return (
            perception.context in {"home", "home_canonical", "canonical_home"}
            and not perception.invalidated_after_input
            and not any(
                item.casefold() in FORBIDDEN_NAVIGATION_ACTIONS
                for item in perception.negative_evidence
            )
        )

    @staticmethod
    def _family_values(perception: PerceptionEnvelope | None) -> Mapping[str, Any]:
        if perception is None:
            return {}
        facts = perception.facts_for("campaign")
        return {} if facts is None else facts.values

    def plan(
        self,
        facts: SchedulerFacts,
        perception: PerceptionEnvelope | None = None,
    ) -> CampaignNavigationPlan | NormalizedResult:
        if perception is None:
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "CAMPAIGN_PERCEPTION_REQUIRED",
                verified=False,
            )
        values = self._family_values(perception)
        decision = plan_shared_campaign_destination_navigation(
            consumer="campaign_stage",
            destination_id=self.destination,
            localization=values.get("localization"),
            binding=values.get("binding"),
            atlas=values.get("atlas"),
        )
        return CampaignNavigationPlan(self.destination, decision)

    def reconcile(
        self,
        plan: CampaignNavigationPlan | NormalizedResult,
        perception: PerceptionEnvelope | None = None,
    ) -> NormalizedResult:
        if isinstance(plan, NormalizedResult):
            return plan
        decision = plan.decision
        terminal = getattr(decision, "terminal", "")
        if terminal == ZERO_TRANSPORT_REPLAY_COMPLETE:
            return NormalizedResult(
                NormalizedOutcome.COMPLETE_FOR_RESET,
                "CAMPAIGN_NAVIGATION_ONLY_COMPLETE",
                observed_progress={"destination": plan.destination, "navigation_only": True},
            )
        if terminal == NAVIGATION_EVIDENCE_REQUIRED:
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "CAMPAIGN_NAVIGATION_EVIDENCE_REQUIRED",
                verified=False,
                observed_progress={"destination": plan.destination},
            )
        if terminal == NAVIGATION_BLOCKED_FAIL_CLOSED:
            return NormalizedResult(
                NormalizedOutcome.BLOCKED,
                "CAMPAIGN_NAVIGATION_BLOCKED_FAIL_CLOSED",
                verified=False,
                observed_progress={"destination": plan.destination},
            )
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "CAMPAIGN_NAVIGATION_UNKNOWN_DECISION",
            verified=False,
        )

    def recover(self, reason_code: str) -> NormalizedResult:
        return NormalizedResult(
            NormalizedOutcome.BLOCKED,
            "CAMPAIGN_NAVIGATION_RECOVERY_REQUIRES_RECOGNIZED_SAFE_EXIT",
            verified=False,
            observed_progress={"reason": reason_code, "transport_count": 0},
        )

    def summarize(self) -> Mapping[str, Any]:
        return {
            "flow_id": CAMPAIGN_FLOW_ID,
            "destination": self.destination,
            "mode": "navigation_only",
            "forbidden_inputs": sorted(FORBIDDEN_CAMPAIGN_INPUTS),
            "transport_count": 0,
            "registration_status": "NOT_REGISTERED",
            "scheduler_eligible": False,
        }


def _epoch(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative clock value")
    return float(value)


def _ap_progress(value: object) -> CampaignRouteProgress:
    integer_fields = {"initial_ap", "current_ap", "completed_runs", "ap_spent", "ap_regenerated"}
    if (not isinstance(value, Mapping) or set(value) != integer_fields | {"loss_seen"}
            or any(type(value[key]) is not int for key in integer_fields)
            or type(value["loss_seen"]) is not bool):
        raise ValueError("Campaign AP progress is not a typed ledger")
    progress = CampaignRouteProgress(**value)
    if progress.current_ap != progress.initial_ap - progress.ap_spent + progress.ap_regenerated:
        raise ValueError("Campaign AP progress does not conserve the observed balance")
    return progress


def _completed_drain_progress(result) -> CampaignRouteProgress:
    """A completed route accounts for every battle and leaves no affordable AP."""
    stage = result.get("destination")
    cost = result.get("ap_cost")
    if stage not in CAMPAIGN_AP_COSTS or type(cost) is not int or cost != CAMPAIGN_AP_COSTS[stage]:
        raise ValueError("Campaign AP destination/cost is not exact")
    progress = _ap_progress(result.get("progress"))
    count = progress.completed_runs
    if (type(result.get("ap_before")) is not int or type(result.get("ap_after")) is not int
            or progress.initial_ap != result.get("ap_before") or progress.current_ap != result.get("ap_after")
            or any(type(result.get(key)) is not int or result[key] != count for key in (
                "stage_entry_transport_count", "new_battle_count", "committed_ap_effect_count"))
            or not campaign_ap_drain_verified(stage, progress,
                battle_outcome=result.get("battle_outcome"),
                result_successor_verified=result.get("result_successor_verified"),
                terminal_home_verified=result.get("terminal_home_verified"),
                refill_seen=result.get("refill_seen", False))):
        raise ValueError("Campaign AP drain, exact Victory ledger, and canonical Home are not verified")
    return progress


def _confirmed_effect_count(result, stage: str) -> int:
    """Keep prior reconciled victories when a later attempt cannot be resolved."""
    try:
        progress = _ap_progress(result.get("progress"))
        count = result.get("committed_ap_effect_count")
        entries, battles = result.get("stage_entry_transport_count"), result.get("new_battle_count")
        if (result.get("destination") == stage and type(result.get("ap_cost")) is int
                and result["ap_cost"] == CAMPAIGN_AP_COSTS[stage]
                and type(count) is int and count == progress.completed_runs
                and type(entries) is int and type(battles) is int
                and 0 <= count <= battles <= entries <= CAMPAIGN_DRAIN_MAX_RUNS
                and 0 <= progress.initial_ap <= 120 and 0 <= progress.current_ap <= 120
                and progress.ap_spent == count * CAMPAIGN_AP_COSTS[stage]):
            return count
    except (TypeError, ValueError):
        pass
    return 0


@dataclass(frozen=True)
class CampaignApAdmission:
    """One capture-only Home AP observation; never an execution permission."""

    identity: SchedulerIdentity
    stage_identity: str
    ap_current: int
    observed_at_utc: float
    captured_monotonic: float
    frame_sha256: str
    frame_path: str
    profile_id: str = CAMPAIGN_PROFILE_ID

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SchedulerIdentity) or self.identity.task_id != CAMPAIGN_AP_FLOW_ID:
            raise ValueError("Campaign AP admission requires its exact task identity")
        if self.stage_identity not in CAMPAIGN_AP_COSTS:
            raise ValueError("Campaign AP admission stage is not approved")
        if type(self.ap_current) is not int or not 0 <= self.ap_current <= 120:
            raise ValueError("Campaign AP admission balance is invalid")
        _epoch(self.observed_at_utc, "observed_at_utc")
        _epoch(self.captured_monotonic, "captured_monotonic")
        if (type(self.frame_sha256) is not str or len(self.frame_sha256) != 64
                or any(char not in "0123456789abcdef" for char in self.frame_sha256)
                or type(self.frame_path) is not str or not self.frame_path.strip()
                or self.profile_id != CAMPAIGN_PROFILE_ID):
            raise ValueError("Campaign AP admission capture/profile binding is invalid")

    def projection(self, *, generation: str, next_eligible_at: float | None = None) -> RecurrenceProjection:
        self.__post_init__()
        if type(generation) is not str or not generation or generation != generation.strip():
            raise ValueError("Campaign AP projection requires a canonical occurrence generation")
        return RecurrenceProjection(
            RecurrenceClass.AP_REGENERATION, observed_at_utc=self.observed_at_utc,
            observed_balance=self.ap_current, generation=generation, next_eligible_at=next_eligible_at,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "account_id": self.identity.account_id, "server_id": self.identity.server_id,
            "reset_id": self.identity.reset_id, "task_id": self.identity.task_id,
            "stage_identity": self.stage_identity, "ap_current": self.ap_current,
            "observed_at_utc": self.observed_at_utc, "captured_monotonic": self.captured_monotonic,
            "frame_sha256": self.frame_sha256, "frame_path": self.frame_path, "profile_id": self.profile_id,
        }


class CampaignExecutionHandler(CampaignApSelectionHandler):
    """AP execution is installed explicitly; the navigation-only handler stays separate."""

    selection_only = False
    max_inputs = CAMPAIGN_MAX_INPUTS
    max_actions = CAMPAIGN_DRAIN_MAX_RUNS

    def __init__(self, snapshot, execute, *, stage: str = "1-15-9") -> None:
        super().__init__(snapshot)
        parse_supported_campaign_story_destination(stage)
        # Low-AP due checks must reach the runner's zero-input Home deferral
        # so completion advances the cadence instead of repeatedly observing AP.
        self.minimum_observed_ap = 0
        self._execute = execute

    def describe(self):
        return replace(super().describe(), allows_pending_resource_observation=True)

    def execute_run(self, run, facts, perception=None):
        return self._execute(run, facts)


class CampaignApRunnerError(RuntimeError):
    def __init__(self, reason: str, partial_result: Mapping[str, object]) -> None:
        super().__init__(reason)
        self.partial_result = dict(partial_result)


def is_clean_home_frame(frame) -> bool:
    from scripts.startup_normalization import is_clean_home_frame as verify
    return verify(frame)


class CampaignRunner:
    """Drain affordable AP under the service's existing owner and run marker.

    Construction has no device or state effects. The caller installs its durable
    interruption marker before execution and supplies the current canonical
    checkpoint. Unknown results never authorize a second pass or a recovery.
    """

    def __init__(self, *, adb: str, serial: str, output_directory: Path,
                 cadence_seconds: float, stage: str = "1-15-9", utc_clock=time.time,
                 monotonic_clock=time.monotonic, settle_seconds: float = 1.0) -> None:
        self.stage = parse_supported_campaign_story_destination(stage).identity
        self.target_stage = parse_supported_campaign_story_destination(stage)
        self.config = CampaignAutoBattleConfig(target_stage=self.target_stage,
            ap_cost=CAMPAIGN_AP_COSTS[self.stage],
            ap_budget=CAMPAIGN_AP_COSTS[self.stage] * CAMPAIGN_DRAIN_MAX_RUNS,
            max_runs=CAMPAIGN_DRAIN_MAX_RUNS)
        self.cadence_seconds = _epoch(cadence_seconds, "cadence_seconds")
        if self.cadence_seconds <= 0:
            raise ValueError("Campaign AP observation cadence must be positive")
        self.settle_seconds = _epoch(settle_seconds, "settle_seconds")
        self.adb, self.serial, self.output_directory = adb, serial, Path(output_directory)
        self.utc_clock, self.monotonic_clock = utc_clock, monotonic_clock

    def _identity(self, identity: SchedulerIdentity) -> None:
        _epoch(self.utc_clock(), "utc_clock")
        if not isinstance(identity, SchedulerIdentity) or identity.task_id != CAMPAIGN_AP_FLOW_ID:
            raise ValueError("Campaign AP requires its typed claim identity")
        identity.__post_init__()
        # Ordinary AP belongs to the claimed occurrence, which may span UTC midnight.

    def _connect(self, checkpoint, workflow):
        from scripts.bluestacks_native_runtime import LocalBlueStacksRuntime
        checkpoint()
        runtime = LocalBlueStacksRuntime.connect(adb=self.adb, serial=self.serial,
            output_directory=self.output_directory, workflow=workflow, execute=True)
        runtime.max_inputs = CAMPAIGN_MAX_INPUTS
        runtime.checkpoint = checkpoint
        return runtime

    def _read_home(self, runtime, identity, checkpoint, label, *, captured=None) -> CampaignApAdmission:
        if captured is None:
            captured = runtime.capture(label)
        observed_at = _epoch(self.utc_clock(), "utc_clock")
        found = recognize_campaign_frame(captured.frame, self.target_stage)
        facts = found.observation
        if (not is_clean_home_frame(captured.frame) or not facts.recognized
                or facts.screen is not CampaignScreen.HOME_BASE
                or facts.overlay_state not in {"none", "none_observed"}
                or type(facts.ap_current) is not int or not 0 <= facts.ap_current <= 120
                or found.frame_sha256 != hashlib.sha256(captured.frame.tobytes()).hexdigest()
                or runtime.measure_foreground_package() != "com.global.ztmslg"):
            raise ValueError("Campaign AP requires a current canonical Home and icon-bound AP balance")
        checkpoint()
        self._identity(identity)
        return CampaignApAdmission(identity, self.stage, facts.ap_current, observed_at,
                                   captured.captured_monotonic, captured.sha256, str(captured.path))

    def _annotate(self, identity, runtime, result) -> dict[str, object]:
        result = dict(result)
        completed = _epoch(self.utc_clock(), "utc_clock")
        total = runtime.input_count if runtime is not None else 0
        stage, battle = result.get("stage_entry_transport_count"), result.get("new_battle_count")
        valid = (type(total) is int and 0 <= total <= CAMPAIGN_MAX_INPUTS
                 and type(stage) is int and 0 <= stage <= CAMPAIGN_DRAIN_MAX_RUNS
                 and type(battle) is int and 0 <= battle <= stage <= battle + 1
                 and result.get("accounting_verified") is not False)
        for key in ("total_input_count", "input_count"):
            if key in result and (type(result[key]) is not int or result[key] != total):
                result.setdefault("native_reported_input_count", result[key])
                valid = False
        if "campaign_dispatch_count" in result and (
                type(result["campaign_dispatch_count"]) is not int
                or type(stage) is not int or type(battle) is not int
                or result["campaign_dispatch_count"] != max(stage, battle)):
            result.setdefault("native_reported_dispatch_count", result["campaign_dispatch_count"])
            valid = False
        result.setdefault("destination", self.stage)
        result.setdefault("ap_cost", self.config.ap_cost)
        result.update(account_id=identity.account_id, server_id=identity.server_id, reset_id=identity.reset_id,
            task_id=CAMPAIGN_AP_FLOW_ID,
            runtime_profile_id=CAMPAIGN_PROFILE_ID, time_basis="utc", completed_at_utc=completed,
            total_input_count=total, input_count=total, accounting_verified=valid,
            campaign_dispatch_count=max(stage, battle) if valid else None,
            cadence_seconds=self.cadence_seconds,
            next_eligible_at=(completed + self.cadence_seconds
                              if result.get("status") in {"completed", "deferred"} else None))
        return result

    def _no_resource_attempt(self, result) -> bool:
        if (result.get("accounting_verified") is not True
                or result.get("effect_reconciliation_required") is not False
                or result.get("destination") != self.stage
                or type(result.get("ap_cost")) is not int or result["ap_cost"] != self.config.ap_cost
                or any(type(result.get(key)) is not int or result[key] != 0 for key in (
                    "campaign_dispatch_count", "stage_entry_transport_count",
                    "new_battle_count", "committed_ap_effect_count"))):
            return False
        try:
            progress = _ap_progress(result.get("progress"))
        except (TypeError, ValueError):
            return False
        before, after = result.get("ap_before"), result.get("ap_after")
        return bool(type(before) is int and type(after) is int and 0 <= before <= 120
                    and before == after == progress.initial_ap == progress.current_ap
                    and progress.ap_spent == progress.ap_regenerated == progress.completed_runs == 0
                    and progress.loss_seen is False)

    def _zero_input_no_effect(self, runtime, result) -> bool:
        """Retain a native no-effect finding only with exact zero-input accounting."""
        return bool(runtime is not None and type(runtime.input_count) is int and runtime.input_count == 0
                    and self._no_resource_attempt(result)
                    and all(type(result.get(key)) is int and result[key] == 0
                            for key in ("total_input_count", "input_count"))
                    and ("navigation_input_count" not in result or (
                        type(result["navigation_input_count"]) is int and result["navigation_input_count"] == 0)))

    def _camera_only_no_effect(self, runtime, result, identity, checkpoint, initial):
        """Inspect only this run's exact camera journal, then read fresh Home/AP."""
        total = runtime.input_count
        if (not self._no_resource_attempt(result) or type(total) is not int or not 1 <= total <= 4
                or any(type(result.get(key)) is not int or result[key] != total
                       for key in ("total_input_count", "input_count", "navigation_input_count"))
                or not isinstance(initial, CampaignApAdmission) or initial.ap_current != result["ap_before"]):
            return None
        events = Path(runtime.events)
        events.resolve().relative_to(runtime.session.resolve())
        if events.is_symlink():
            return None
        journal = events.read_bytes()
        rows = [json.loads(line) for line in journal.splitlines() if line.strip()]
        from scripts.home_atlas_bluestacks import bluestacks_direct_pan_contract
        _, calibration = bluestacks_direct_pan_contract()
        keys, latest_capture = [], 0.0
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or row.get("type") not in {"capture", "dispatch"}:
                raise ValueError("Campaign camera journal contains an unknown event")
            if row["type"] == "capture":
                captured_at = _epoch(row.get("captured_monotonic"), "camera capture monotonic")
                if captured_at < latest_capture:
                    raise ValueError("Campaign camera journal capture order is invalid")
                latest_capture = captured_at
                continue
            if (row.get("target_identity") != "home-camera-click-drag" or row.get("gesture") != "swipe"
                    or row.get("action_class") != "navigation" or row.get("consequence_class") != "navigation_only"
                    or row.get("consequential") is not False or row.get("execute") is not True
                    or not isinstance(row.get("action_key"), str) or not row["action_key"].startswith("nav-pan:")):
                raise ValueError("Campaign camera journal contains a non-camera input")
            start, end = row.get("start"), row.get("end")
            if (type(start) not in (list, tuple) or type(end) not in (list, tuple)
                    or len(start) != 2 or len(end) != 2
                    or any(type(value) is not int for point in (start, end) for value in point)
                    or tuple(start) != calibration.drag_origin
                    or type(row.get("duration_ms")) is not int or row["duration_ms"] != 500
                    or not calibration.drag_bounds[0] <= end[0] <= calibration.drag_bounds[2]
                    or not calibration.drag_bounds[1] <= end[1] <= calibration.drag_bounds[3]
                    or abs(end[0] - start[0]) > calibration.maximum_drag_x
                    or abs(end[1] - start[1]) > calibration.maximum_drag_y
                    or math.dist(start, end) < calibration.minimum_drag_px):
                raise ValueError("Campaign camera journal contains an uncalibrated gesture")
            source = rows[index - 1] if index else {}
            if (latest_capture < initial.captured_monotonic
                    or source.get("type") != "capture" or source.get("label") != "navigate-pan-pre-dispatch"
                    or source.get("sha256") != row.get("source_sha256")):
                raise ValueError("Campaign camera input lacks its immediate source capture")
            path = Path(source["path"])
            path.resolve().relative_to(runtime.session.resolve())
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("Campaign camera source PNG does not match its journal")
            keys.append(row["action_key"])
        if (len(keys) != total or len(set(keys)) != total or type(runtime.action_keys) is not set
                or runtime.action_keys != set(keys)):
            raise ValueError("Campaign camera journal does not account for every actual input")
        home = self._read_home(runtime, identity, checkpoint, "campaign-service-failed-camera-home")
        appended = events.read_bytes()
        if (runtime.input_count != total or runtime.action_keys != set(keys) or not appended.startswith(journal)
                or home.captured_monotonic <= latest_capture or home.ap_current != initial.ap_current):
            raise ValueError("Campaign fresh Home/AP does not prove unchanged camera-only progress")
        new_rows = [json.loads(line) for line in appended[len(journal):].splitlines() if line.strip()]
        if (len(new_rows) != 1 or new_rows[0].get("type") != "capture"
                or new_rows[0].get("sha256") != home.frame_sha256
                or new_rows[0].get("path") != home.frame_path):
            raise ValueError("Campaign fresh Home/AP capture is not the only journal successor")
        return {"input_authority": False, "camera_inputs": total, "action_keys": keys,
                "journal_sha256_before_home_capture": hashlib.sha256(journal).hexdigest(),
                "home_ap_observation": home.to_mapping()}

    def _normalization_ledger(self, runtime, journal_before, count_before, final_frame, phase):
        """Bind each normalization dispatch to its retained, recognized source and successor."""
        import cv2
        import numpy as np
        from scripts.bluestacks_popup_recognition import recognize_reset_popup
        from scripts.startup_recovery import (_contextual_exact_vip, _contextual_target,
            VIP_RESET_TARGET)
        from scripts.startup_surface_recognition import (recognize_startup_surface,
            is_exact_scarlett_recognition, SCARLETT_SAFE_BACK_TARGET_IDENTITY)
        def checkpoint():
            if getattr(runtime, "checkpoint", None) is not None:
                runtime.checkpoint()
        checkpoint()
        events = Path(runtime.events)
        events.resolve().relative_to(runtime.session.resolve())
        if events.is_symlink():
            raise ValueError("Campaign normalization journal is a symlink")
        data = events.read_bytes()
        if not data.startswith(journal_before):
            raise ValueError("Campaign normalization journal changed")
        rows = [json.loads(line) for line in data[len(journal_before):].splitlines() if line.strip()]
        dispatches = [i for i, row in enumerate(rows) if row.get("type") == "dispatch"]
        count = runtime.input_count - count_before
        if count != len(dispatches) or count < 0 or count > (6 if phase == "initial" else 1):
            raise ValueError("Campaign normalization count does not match native journal")
        allowed = {
            "campaign-lineup-back": CampaignScreen.HERO_LINEUP,
            "campaign-stage-dialog-close": CampaignScreen.STAGE_DIALOG,
            "campaign-chapter-back": CampaignScreen.CHAPTER_MAP,
            "campaign-base-request": CampaignScreen.TIER_MAP,
            "campaign-exit-base": CampaignScreen.TIER_MAP,
        }
        successors = {
            "campaign-lineup-back": {CampaignScreen.STAGE_DIALOG, CampaignScreen.CHAPTER_MAP},
            "campaign-stage-dialog-close": {CampaignScreen.CHAPTER_MAP},
            "campaign-chapter-back": {CampaignScreen.TIER_MAP},
            "campaign-base-request": {CampaignScreen.TIER_MAP},
            "campaign-exit-base": {CampaignScreen.HOME_BASE},
        }
        def load_capture(row):
            checkpoint()
            if row.get("type") != "capture":
                raise ValueError("Campaign normalization capture missing")
            path = Path(row["path"])
            path.resolve().relative_to(runtime.session.resolve())
            if path.is_symlink():
                raise ValueError("Campaign normalization capture is a symlink")
            png = path.read_bytes()
            if hashlib.sha256(png).hexdigest() != row.get("sha256"):
                raise ValueError("Campaign normalization capture hash mismatch")
            frame = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError("Campaign normalization capture cannot be decoded")
            checkpoint()
            return frame, png
        final_rows = [row for row in rows if row.get("type") == "capture"
                      and row.get("path") == str(final_frame.path) and row.get("sha256") == final_frame.sha256]
        if not final_rows:
            raise ValueError("Campaign normalization final frame is not journal-bound")
        load_capture(final_rows[-1])
        ledger = []
        keys = set()
        for pos, index in enumerate(dispatches):
            row = rows[index]
            if index == 0 or rows[index - 1].get("type") != "capture":
                raise ValueError("Campaign normalization dispatch lacks immediate capture")
            source = rows[index - 1]
            image, png = load_capture(source)
            key, target = row.get("action_key"), row.get("target_identity")
            roi = row.get("target_roi")
            if (source.get("sha256") != row.get("source_sha256") or not isinstance(key, str)
                    or not key or key in keys or row.get("execute") is not True
                    or row.get("action_class") != "navigation" or row.get("consequential") is not False
                    or row.get("continuation_of") is not None):
                raise ValueError("Campaign normalization dispatch is not exact")
            if not isinstance(runtime.action_keys, set) or key not in runtime.action_keys:
                raise ValueError("Campaign normalization action key is absent from runtime")
            keys.add(key)
            popup = recognize_reset_popup(image)
            surface = recognize_startup_surface(image, png)
            checkpoint()
            if target == VIP_RESET_TARGET:
                expected_key = "campaign-initial-startup-overlay" if phase == "initial" else "campaign-terminal-startup-overlay"
                if not _contextual_exact_vip(popup) or tuple(roi or ()) != _contextual_target(popup) or key != expected_key:
                    raise ValueError("Campaign VIP normalization source or target mismatch")
                kind = "VIP_POINTS_GET_PTS"
            elif target == SCARLETT_SAFE_BACK_TARGET_IDENTITY:
                expected_key = "campaign-initial-startup-overlay" if phase == "initial" else "campaign-terminal-startup-overlay"
                if (not is_exact_scarlett_recognition(surface) or surface.get("frame_sha256") != source["sha256"]
                        or tuple(roi or ()) != tuple(surface.get("safe_exit_roi") or ()) or key != expected_key):
                    raise ValueError("Campaign Scarlett normalization source or target mismatch")
                kind = "SCARLETT_THREE_DAY_PACK"
            else:
                found = recognize_campaign_frame(image, self.target_stage)
                targets = dict(found.targets)
                if (phase != "initial" or target not in allowed or found.observation.recognized is not True
                        or found.observation.screen != allowed[target]
                        or found.observation.overlay_state not in {"none", "none_observed"}
                        or target not in targets or tuple(roi or ()) != tuple(targets[target])
                        or not key.startswith(target + "-")):
                    raise ValueError("Campaign Home normalization source or target mismatch")
                kind = found.observation.screen.name
            stop = dispatches[pos + 1] if pos + 1 < len(dispatches) else len(rows)
            candidates = [candidate for candidate in rows[index + 1:stop] if candidate.get("type") == "capture"]
            successor = None
            for candidate in candidates:
                candidate_image, candidate_png = load_capture(candidate)
                detail = recognize_reset_popup(candidate_image)
                overlay = recognize_startup_surface(candidate_image, candidate_png)
                found = recognize_campaign_frame(candidate_image, self.target_stage)
                checkpoint()
                if (not detail.get("recognized") and not detail.get("blocking_unknown_modal")
                        and not overlay.get("recognized") and not overlay.get("commercial_looking")
                        and found.observation.recognized is True
                        and found.observation.screen in {CampaignScreen.HOME_BASE, CampaignScreen.CHAPTER_MAP,
                            CampaignScreen.TIER_MAP, CampaignScreen.STAGE_DIALOG, CampaignScreen.HERO_LINEUP}
                        and found.observation.overlay_state in {"none", "none_observed"}
                        and (target not in successors or found.observation.screen in successors[target])
                        and float(candidate["captured_monotonic"]) > float(source["captured_monotonic"])):
                    successor = candidate
                    break
            if successor is None:
                raise ValueError("Campaign normalization lacks a fresh recognized successor")
            ledger.append({"phase": phase, "source": source, "successor": successor,
                           "surface": kind, "action_key": key, "target": target, "target_roi": roi,
                           "native_before": count_before + pos, "native_after": count_before + pos + 1})
        checkpoint()
        return {"phase": phase, "native_before": count_before, "native_after": runtime.input_count,
                "input_count": count, "dispatches": ledger,
                "settled_path": str(final_frame.path), "settled_sha256": final_frame.sha256}

    def __call__(self, identity, previous_reset_id, checkpoint):
        from scripts.bluestacks_campaign_ap import CampaignStageChallengeBoundary, run_campaign_ap_route
        from scripts.navigation_development_boundary import open_canonical_action_store
        self._identity(identity)
        runtime = None
        store = None
        leased = False
        result = {"status": "unresolved", "stage_entry_transport_count": 0,
                  "new_battle_count": 0, "committed_ap_effect_count": 0}
        owner = None
        failure = None
        failure_cause = None
        initial = None
        no_effect_proven = False
        try:
            runtime = self._connect(checkpoint, f"campaign-ap-{self.stage}")
            store = open_canonical_action_store()
            owner = f"automation-service:campaign:{runtime.session.name}"
            store.acquire_lease(owner, self.utc_clock(), 3600.0)
            leased = True

            def native_checkpoint():
                checkpoint()
                self._identity(identity)
                if not store.lease_valid_for(owner, self.utc_clock()):
                    raise RuntimeError("Campaign AP action lease lost")

            runtime.checkpoint = native_checkpoint
            from scripts.startup_recovery import recover_contextual_startup_overlay
            from scripts.flow_delivery_campaign_bluestacks import _ensure_home_surface_before_prep

            def recognized_parent(captured):
                found = recognize_campaign_frame(captured.frame, self.target_stage)
                return (found.observation.recognized is True
                        and found.observation.screen in {CampaignScreen.HOME_BASE, CampaignScreen.CHAPTER_MAP,
                            CampaignScreen.TIER_MAP, CampaignScreen.STAGE_DIALOG, CampaignScreen.HERO_LINEUP}
                        and found.observation.overlay_state in {"none", "none_observed"})

            def normalize_overlay(captured, *, terminal=False):
                before_count = runtime.input_count
                old_max = runtime.max_inputs
                runtime.max_inputs = min(old_max, before_count + (1 if terminal else 6))
                try:
                    recovered = recover_contextual_startup_overlay(runtime, captured,
                        source_context="campaign-home" if terminal else "campaign-startup",
                        recognize_successor=(lambda frame: recognized_parent(frame)
                            and (not terminal or is_clean_home_frame(frame.frame))),
                        action_key="campaign-terminal-startup-overlay" if terminal else "campaign-initial-startup-overlay",
                        settle_seconds=self.settle_seconds)
                finally:
                    runtime.max_inputs = old_max
                if not recovered.resume_ready or recovered.settled_frame is None:
                    raise ValueError("Campaign startup successor is not positively recognized: " + recovered.reason)
                return recovered.settled_frame

            initial_journal = Path(runtime.events).read_bytes() if Path(runtime.events).exists() else b""
            initial_count = runtime.input_count
            initial_frame = normalize_overlay(runtime.capture("campaign-service-startup"))
            if not is_clean_home_frame(initial_frame.frame):
                _ensure_home_surface_before_prep(runtime.session, runtime=runtime,
                    max_inputs=6 - runtime.input_count, probe_stage=self.target_stage)
            initial_frame = runtime.capture("campaign-service-initial-normalization-settled")
            initial = self._read_home(runtime, identity, native_checkpoint, "campaign-service-initial-home", captured=initial_frame)
            initial_ledger = self._normalization_ledger(runtime, initial_journal, initial_count, initial_frame, "initial")
            if initial.ap_current < self.config.ap_cost:
                result.update(status="deferred", reason="current Home AP is below the exact stage cost",
                    ap_before=initial.ap_current, ap_after=initial.ap_current, terminal_home_verified=True,
                    effect_reconciliation_required=False, identical_retry_denied=False,
                    result_successor_verified=False, battle_outcome=None, home_ap_observation=initial.to_mapping(),
                    initial_normalization=initial_ledger, route_input_count=0)
            else:
                boundary = CampaignStageChallengeBoundary(runtime, store, self.config, owner=owner,
                    game_day_id=identity.reset_id, monotonic_clock=self.monotonic_clock,
                    utc_clock=self.utc_clock, settle_seconds=self.settle_seconds)
                terminal_home = None
                terminal_ledger = None

                def normalize_terminal(_captured):
                    nonlocal terminal_ledger
                    journal = Path(runtime.events).read_bytes()
                    before = runtime.input_count
                    frame = normalize_overlay(runtime.capture("campaign-terminal-normalization-source"), terminal=True)
                    terminal_ledger = self._normalization_ledger(runtime, journal, before, frame, "terminal")
                    return frame

                def terminal_home_ap_reader(captured):
                    nonlocal terminal_home
                    terminal_home = self._read_home(runtime, identity, native_checkpoint,
                        "campaign-service-terminal-home", captured=captured)
                    return terminal_home.ap_current

                result = run_campaign_ap_route(runtime, self.config, checkpoint=native_checkpoint,
                    stage_challenge_boundary=boundary, post_input_delay=self.settle_seconds,
                    monotonic_clock=self.monotonic_clock, terminal_home_ap_reader=terminal_home_ap_reader,
                    terminal_home_normalizer=normalize_terminal)
                result.update(initial_normalization=initial_ledger, terminal_normalization=terminal_ledger)
                if (result.get("destination") != self.stage or type(result.get("ap_cost")) is not int
                        or result["ap_cost"] != self.config.ap_cost):
                    raise ValueError("Campaign native destination/cost does not match the requested route")
                if result.get("status") != "completed":
                    raise ValueError(str(result.get("reason") or "Campaign AP route is not verified"))
                if (not isinstance(terminal_ledger, Mapping)
                        or terminal_ledger.get("native_before", -1) < initial_ledger["native_after"]
                        or terminal_ledger.get("native_after") != runtime.input_count
                        or result.get("total_input_count") != runtime.input_count
                        or result.get("input_count") != runtime.input_count):
                    raise ValueError("Campaign normalization and cumulative native accounting disagree")
                native_checkpoint()
                if (not isinstance(terminal_home, CampaignApAdmission)
                        or result.get("terminal_home_frame") != terminal_home.frame_path
                        or result.get("terminal_home_sha256") != terminal_home.frame_sha256):
                    raise ValueError("Campaign completion does not bind the service-verified terminal Home")
                home = terminal_home
                progress = _ap_progress(result.get("progress"))
                if result.get("ap_before") != progress.initial_ap or result.get("ap_after") != progress.current_ap:
                    raise ValueError("Campaign native balance aliases disagree with its ledger")
                progress = reconcile_observed_ap(progress, ap_observed=home.ap_current)
                result.update(progress=progress.__dict__, ap_after=progress.current_ap,
                              home_ap_observation=home.to_mapping())
                _completed_drain_progress(result)
                result.update(committed_ap_effect_count=progress.completed_runs, terminal_home_verified=True,
                              effect_reconciliation_required=False, identical_retry_denied=False)
            native_checkpoint()
        except Exception as exc:
            partial = getattr(exc, "partial_result", None)
            if isinstance(partial, Mapping):
                result = dict(partial)
            result = self._annotate(identity, runtime, result)
            no_effect_proven = self._zero_input_no_effect(runtime, result)
            if not no_effect_proven and initial is not None:
                try:
                    proof = self._camera_only_no_effect(runtime, result, identity, native_checkpoint, initial)
                    if proof is not None:
                        result.update(camera_only_no_effect_proof=proof, terminal_home_verified=True,
                                      home_ap_observation=proof["home_ap_observation"])
                        no_effect_proven = True
                except Exception as inspection_error:
                    result["no_effect_inspection_error"] = str(inspection_error)
            result = self._annotate(identity, runtime, result)
            result.update(status="unresolved", reason=str(exc), effect_reconciliation_required=not no_effect_proven,
                          identical_retry_denied=True, committed_ap_effect_count=_confirmed_effect_count(result, self.stage),
                          next_eligible_at=None)
            failure = CampaignApRunnerError(str(exc), result)
            failure_cause = exc
        finally:
            if store is not None:
                cleanup_errors = []
                try:
                    if leased:
                        store.release_lease(owner, self.utc_clock())
                except Exception as exc:
                    cleanup_errors.append(f"action lease release: {exc}")
                try:
                    store.close()
                except Exception as exc:
                    cleanup_errors.append(f"action store close: {exc}")
                if cleanup_errors:
                    reason = "; ".join(([str(failure)] if failure else []) + cleanup_errors)
                    result = dict(failure.partial_result) if failure else result
                    result.update(status="unresolved", reason=reason, effect_reconciliation_required=not no_effect_proven,
                                  identical_retry_denied=True)
                    failure = CampaignApRunnerError(reason, self._annotate(identity, runtime, result))
        if failure is not None:
            raise failure from failure_cause
        return self._annotate(identity, runtime, result)


def _verified_deferred_normalization(result, inputs):
    ledger = result.get("initial_normalization")
    home = result.get("home_ap_observation")
    if (not isinstance(ledger, Mapping) or ledger.get("phase") != "initial"
            or ledger.get("native_before") != 0 or ledger.get("native_after") != inputs
            or ledger.get("input_count") != inputs or type(inputs) is not int or not 0 <= inputs <= 6
            or result.get("route_input_count") != 0 or result.get("terminal_normalization") is not None
            or not isinstance(home, Mapping) or ledger.get("settled_path") != home.get("frame_path")
            or ledger.get("settled_sha256") != home.get("frame_sha256")):
        return False
    entries = ledger.get("dispatches")
    if not isinstance(entries, list) or len(entries) != inputs:
        return False
    allowed = {"reset-popup-close", "scarlett-three-day-pack-in-game-back", "campaign-lineup-back",
               "campaign-stage-dialog-close", "campaign-chapter-back", "campaign-base-request",
               "campaign-exit-base"}
    keys = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            return False
        source, successor, key = entry.get("source"), entry.get("successor"), entry.get("action_key")
        if (entry.get("phase") != "initial" or entry.get("native_before") != index
                or entry.get("native_after") != index + 1 or entry.get("target") not in allowed
                or not isinstance(key, str) or not key or key in keys
                or not isinstance(source, Mapping) or not isinstance(successor, Mapping)
                or not source.get("path") or not source.get("sha256")
                or not successor.get("path") or not successor.get("sha256")):
            return False
        keys.add(key)
    return True


def campaign_next_due(result, identity, started_at: float) -> float:
    """Wait after a completed AP drain or an actual insufficient-AP Home observation."""
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != CAMPAIGN_AP_FLOW_ID:
        raise ValueError("Campaign AP outcome requires its exact task identity")
    completed = _epoch(result.get("completed_at_utc"), "completed_at_utc")
    started_at = _epoch(started_at, "started_at")
    cadence = _epoch(result.get("cadence_seconds"), "cadence_seconds")
    due = _epoch(result.get("next_eligible_at"), "next_eligible_at")
    if (result.get("time_basis") != "utc" or completed < started_at or cadence <= 0
            or due != completed + cadence or result.get("terminal_home_verified") is not True
            or result.get("accounting_verified") is not True or result.get("effect_reconciliation_required")
            or result.get("identical_retry_denied") or result.get("runtime_profile_id") != CAMPAIGN_PROFILE_ID
            or (result.get("account_id"), result.get("server_id"), result.get("reset_id"), result.get("task_id")) != (
                identity.account_id, identity.server_id, identity.reset_id, CAMPAIGN_AP_FLOW_ID)):
        raise ValueError("Campaign AP outcome, identity, or UTC cadence is not verified")
    stage = result.get("destination")
    if (stage not in CAMPAIGN_AP_COSTS or type(result.get("ap_cost")) is not int
            or result["ap_cost"] != CAMPAIGN_AP_COSTS[stage]):
        raise ValueError("Campaign AP destination/cost is not exact")
    inputs = result.get("total_input_count")
    fields = (result.get("campaign_dispatch_count"), result.get("stage_entry_transport_count"),
              result.get("new_battle_count"), result.get("committed_ap_effect_count"))
    if (type(inputs) is not int or not 0 <= inputs <= CAMPAIGN_MAX_INPUTS
            or any(type(value) is not int or not 0 <= value <= CAMPAIGN_DRAIN_MAX_RUNS for value in fields)
            or not fields[2] <= fields[1] <= fields[2] + 1 or fields[3] > fields[2]
            or fields[0] != max(fields[1:3]) or inputs < fields[1] + fields[2]):
        raise ValueError("Campaign AP input/action accounting is invalid")
    if result.get("status") == "deferred":
        before, after = result.get("ap_before"), result.get("ap_after")
        exact_normalization = _verified_deferred_normalization(result, inputs)
        if ((inputs != 0 and not exact_normalization)
                or (inputs == 0 and (result.get("terminal_normalization") is not None
                    or result.get("route_input_count", 0) != 0)) or any(fields) or type(before) is not int or type(after) is not int or before != after
                or not 0 <= before < CAMPAIGN_AP_COSTS[stage]):
            raise ValueError("Campaign AP no-work observation is not exact")
    elif result.get("status") == "completed":
        progress = _completed_drain_progress(result)
        if fields[0] != progress.completed_runs:
            raise ValueError("Campaign AP drain dispatch count is not exact")
    else:
        raise ValueError("Campaign AP requires inspection before another pass")
    return due
