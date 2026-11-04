"""Guarded native-runner fakes shared by the service route contract and route dispatch modules.

Each fake models one route's native runner contract: it checkpoints before every input,
counts inputs and resource actions, and returns (or raises) the same result shapes the
real runner produces.  No fake touches a device; all hooks are optional.
"""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict
import hashlib
import json

import cv2
import numpy as np

from automation_service import personal_might as personal_might_adapter
from automation_service.bioenhancer import BioenhancerNativePartialResultError, PRODUCT_ID as BIOENHANCER_PRODUCT_ID
from automation_service.campaign import CampaignApRunnerError
from automation_service.enhancement import (
    PRODUCT_ID as ENHANCEMENT_PRODUCT_ID, PRODUCT_REVISION as ENHANCEMENT_PRODUCT_REVISION,
    EnhancementNativePartialResultError,
)
from automation_service.recruitment import recruitment_reset
from automation_service.registry import (
    BIOENHANCER_FLOW_ID, CAMPAIGN_PROFILE_ID, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID,
    RECRUITMENT_FLOW_ID, SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID,
)
from automation_service.service import ServiceError
from automation_service.supply import (
    PRODUCT_ID as SUPPLY_PRODUCT_ID, PRODUCT_REVISION as SUPPLY_PRODUCT_REVISION,
    SupplyNativePartialResultError,
)
from automation_service.ultimate import (
    PRODUCT_ID as ULTIMATE_PRODUCT_ID, PROFILE_ID as ULTIMATE_PROFILE_ID, UltimateRunnerError,
)
from scripts import navigation_development_boundary as boundary
from scripts.bioenhancer_free_research_route import parse_free_research_cooldown
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.noahs_tavern_recruit_maintenance import NoahMaintenanceState
from tasks.runtime_identity import derive_resource_runtime_identity, resource_fixed_runtime_binding


class GuardedSupplyRunner:
    def __init__(self, stop):
        self.stop = stop
        self.calls, self.inputs = [], []
        self.consume, self.partial = False, False
        self.actions = self.effects = 0
        self.on_input = self.on_entry = None

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock):
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry()
        count = holds = 0
        error = None
        try:
            for index in range(4):
                checkpoint()
                self.inputs.append((identity.reset_id, index))
                count += 1
                held = int(self.consume and index == 2)
                holds += held
                self.actions += held
                self.effects += held
                if self.on_input:
                    self.on_input(index)
                if self.partial and holds:
                    raise RuntimeError("native successor lost after free hold")
        except Exception as exc:
            error = exc
        next_reset = (self.stop.now // 86400 + 1) * 86400
        result = {
            "status": "unresolved" if error else "completed",
            "flow_id": SUPPLY_FLOW_ID, "product_id": SUPPLY_PRODUCT_ID,
            "product_revision": SUPPLY_PRODUCT_REVISION, "task_id": SUPPLY_PRODUCT_ID,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "time_basis": "utc",
            "completed_at_utc": self.stop.now, "next_reset_at_utc": next_reset,
            "total_input_count": count, "hold_transport_calls": holds,
            "accounting_verified": True, "no_work": not self.consume,
            "free_attempts_before": 3 if self.consume else 0,
            "free_attempts_after": None if error else 0,
            "terminal_home_verified": error is None,
            "terminal_home_frame": {"frame_path": "current-home.png", "frame_sha256": "a" * 64},
            "effect_reconciliation_required": error is not None and holds > 0,
            "identical_retry_denied": error is not None,
        }
        if error:
            raise SupplyNativePartialResultError(str(error), partial_result=result) from error
        return result


class GuardedUltimateRunner:
    def __init__(self, stop):
        self.stop = stop
        self.completed_reset = recruitment_reset(stop.now)
        self.pending = self.fail_after_flee = False
        self.calls, self.connections, self.inputs = [], [], []
        self.flee_calls = self.actions = 0
        self.on_input = self.on_entry = None

    @property
    def effects(self):
        return self.flee_calls

    def __call__(self, identity, previous_reset, checkpoint):
        checkpoint()
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry()
        already = self.completed_reset == identity.reset_id
        count = attempts = flee = 0
        error = None
        try:
            if self.pending:
                raise RuntimeError("retained daily Flee awaits Home reconciliation")
            self.connections.append(identity.reset_id)
            if not already:
                for index in range(4):
                    checkpoint()
                    self.inputs.append((identity.reset_id, index))
                    count += 1
                    self.actions += 1 - attempts
                    attempts = 1
                    if index == 3:
                        flee = 1
                        self.flee_calls += 1
                        if self.fail_after_flee:
                            self.pending = True
                            raise RuntimeError("Flee dispatched but terminal Home unknown")
                    if self.on_input:
                        self.on_input(index)
                self.completed_reset = identity.reset_id
        except Exception as exc:
            error = exc
        result = {
            "status": "unresolved" if error else "already_completed" if already else "complete_for_reset",
            "flow_id": ULTIMATE_FLOW_ID, "account_id": identity.account_id,
            "server_id": identity.server_id, "reset_id": identity.reset_id,
            "reset_identity": identity.reset_id, "task_id": ULTIMATE_PRODUCT_ID,
            "runtime_profile_id": ULTIMATE_PROFILE_ID, "time_basis": "utc",
            "completed_at_utc": self.stop.now,
            "next_eligible_at": (self.stop.now // 86400 + 1) * 86400,
            "total_input_count": count, "ultimate_dispatch_count": attempts,
            "flee_transport_calls": flee, "committed_action_count": int(not error and not already),
            "accounting_verified": True, "terminal_home_verified": error is None,
            "reset_guard_completed": error is None, "effect_reconciliation_required": error is not None,
            "identical_retry_denied": error is not None,
            "resource_delta": {"ap": 0, "stamina": 0, "currency": 0, "items": 0},
        }
        if error:
            raise UltimateRunnerError(str(error), result) from error
        return result


class GuardedEnhancementRunner:
    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs = [], []
        self.no_work = self.partial = False
        self.retained_count = 0
        self.use_calls = 0
        self.on_entry = self.on_input = None

    @property
    def actions(self):
        return self.use_calls

    effects = actions

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock):
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry()
        count = uses = 0
        error = None
        try:
            if not self.no_work:
                for index in range((3 - self.retained_count) * 2):
                    checkpoint()
                    self.inputs.append((identity.reset_id, index))
                    count += 1
                    if index % 2:
                        uses += 1
                        self.use_calls += 1
                    if self.on_input:
                        self.on_input(index)
                    if self.partial and uses:
                        raise RuntimeError("native successor lost after first Use")
        except Exception as exc:
            error = exc
        native_reset = f"local-{identity.reset_id.removeprefix('game-day-')}-enhancement-family"
        home = {"frame_path": "current-home.png", "frame_sha256": "a" * 64}
        variants = ("gear", "chip", "module")
        retained = list(variants) if self.no_work else list(variants[:self.retained_count])
        current = [variant for variant in variants if variant not in retained]
        runtime = str(self.output / "current-canonical-session")
        topology = "retained_categories_plus_current_home" if self.no_work else "composite" if retained else "continuous"
        sources = {variant: {
            "status": "verified", "variant": variant, "reset_identity": native_reset,
            "runtime_session": str(self.output / "original-family") if variant in retained else runtime,
            "delivery_sha256": "b" * 64,
            "resource_affecting_action_key": f"enhancement:{variant}:enhancement-use:{'retained' if variant in retained else 'current'}",
        } for variant in variants}
        verification = {
            "status": "verified", "proof_topology": topology,
            "categories_verified": list(variants), "current_categories": current, "retained_categories": retained,
            "retained_category_count": len(retained), "current_resource_affecting_dispatch_count": len(current),
            "category_source_proofs": sources,
        }
        result = {
            "status": "unresolved" if error else "already_completed" if self.no_work else "completed",
            "no_work": self.no_work, "flow_id": ENHANCEMENT_FLOW_ID,
            "product_id": ENHANCEMENT_PRODUCT_ID, "product_revision": ENHANCEMENT_PRODUCT_REVISION, "task_id": ENHANCEMENT_PRODUCT_ID,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "native_reset_identity": native_reset,
            "time_basis": "utc", "completed_at_utc": self.stop.now,
            "next_reset_at_utc": (self.stop.now // 86400 + 1) * 86400,
            "total_input_count": count, "input_count": count, "enhancement_dispatch_count": uses,
            "resource_affecting_dispatch_count": uses, "categories_completed": 3,
            "accounting_verified": True, "terminal_home_verified": error is None,
            "terminal_home_frame": home, "family_verification": verification,
            "proof_topology": topology, "session_directory": runtime,
            "effect_reconciliation_required": error is not None and uses > 0,
            "identical_retry_denied": error is not None,
        }
        if self.no_work:
            result.update(
                current_home_proof=dict(home),
                retained_category_proofs=sources,
            )
        if error:
            raise EnhancementNativePartialResultError(str(error), partial_result=result) from error
        return result


class GuardedPersonalMightRunner:
    def __init__(self, stop):
        self.stop = stop
        self.calls, self.inputs, self.backend_identities = [], [], []
        self.no_work = self.partial = False
        self.praise_calls = 0
        self.on_entry = self.on_input = None

    @property
    def actions(self):
        return self.praise_calls

    effects = actions

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock):
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry()
        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(), datetime.fromtimestamp(self.stop.now, timezone.utc),
        )
        self.backend_identities.append(asdict(backend))
        count = praise = 0
        error = None
        try:
            for index in range(5 if self.no_work else 6):
                checkpoint()
                self.inputs.append((identity.reset_id, index))
                count += 1
                if not self.no_work and index == 3:
                    praise = 1
                    self.praise_calls += 1
                if self.on_input:
                    self.on_input(index)
                if self.partial and praise:
                    raise RuntimeError("native gray successor lost after Praise")
        except Exception as exc:
            error = exc
        result = {
            "status": "unresolved" if error else "already_complete" if self.no_work else "complete_for_reset",
            "no_work": self.no_work, "flow_id": PERSONAL_MIGHT_FLOW_ID, "task_id": personal_might_adapter.PRODUCT_ID,
            "runtime_profile_id": personal_might_adapter.PROFILE_ID,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "time_basis": "utc", "completed_at_utc": self.stop.now,
            "next_eligible_at": (self.stop.now // 86400 + 1) * 86400,
            "total_input_count": count, "praise_transport_calls": praise,
            "committed_action_count": int(praise and error is None), "accounting_verified": True,
            "journal_status": "unresolved" if error else "confirmed",
            "action_id": "current-day-canonical-praise", "action_key": personal_might_adapter._key(backend),
            "backend_identity": asdict(backend), "terminal_home_verified": error is None,
            "source_frame": {"frame_path": "source.png", "frame_sha256": "a" * 64},
            "praise_result_frame": {"frame_path": "current-gray.png", "frame_sha256": "b" * 64},
            "terminal_home_frame": {"frame_path": "current-home.png", "frame_sha256": "c" * 64},
            "effect_reconciliation_required": error is not None and praise > 0,
            "identical_retry_denied": error is not None,
        }
        if error:
            raise personal_might_adapter.PersonalMightRunnerError(str(error), partial_result=result) from error
        return result


class GuardedBioenhancerRunner:
    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs = [], []
        self.consume, self.fault = False, None
        self.actions = 0
        self.on_input = self.on_entry = None

    @property
    def effects(self):
        return self.actions

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock):
        checkpoint()
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry()
        count = actions = 0
        current = self.output / f"native-{len(self.calls)}"
        ordinal = 0
        def capture(label):
            nonlocal ordinal
            ordinal += 1
            image = np.full((1280, 800, 3), ordinal, np.uint8)
            raw = cv2.imencode(".png", image)[1].tobytes()
            path = current / f"{ordinal}-{label}.png"
            path.write_bytes(raw)
            return CapturedNativeFrame(image, raw, hashlib.sha256(raw).hexdigest(), float(ordinal), path)

        error = None
        try:
            with boundary.DevelopmentSession(
                owner="bio-test-route", invocation_id=current.name,
                session_directory=current, max_inputs=8,
                runtime_input_lock=runtime_input_lock, checkpoint=checkpoint,
            ) as session:
                for index in range(5):
                    resource = self.consume and index == 2
                    def dispatch(_frame):
                        nonlocal count, actions
                        checkpoint()
                        self.inputs.append((identity.reset_id, index))
                        count += 1
                        actions += int(resource)
                        self.actions += int(resource)
                        if self.on_input:
                            self.on_input(index)
                    session.run_action(action_class="free_action" if resource else "navigation",
                                       label=f"step-{index}", capture=capture, dispatch=dispatch,
                                       recognize=lambda _frame: "known_successor")
                    if self.fault == "partial" and resource:
                        raise RuntimeError("native lost successor after Research")
        except Exception as exc:
            error = exc
        unknown = error is not None or self.fault == "unknown"
        cooldown = parse_free_research_cooldown("Free in 01:00:00", now=datetime.fromtimestamp(self.stop.now, timezone.utc))
        result = {
            "status": "unresolved" if unknown else "completed", "terminal_home_verified": not unknown,
            "cooldown_proof_verified": not unknown, "accounting_verified": True,
            "account_id": identity.account_id, "server_id": identity.server_id, "reset_id": identity.reset_id,
            "time_basis": "utc", "completed_at_utc": self.stop.now,
            "no_work": not self.consume, "total_input_count": count, "free_research_transport_calls": actions,
            "cooldown": cooldown, "next_due_utc": cooldown["next_due_utc"],
            "semantic_postcondition": {"proven": True, "timer_proven": True} if actions else None,
            "effect_reconciliation_required": unknown and actions > 0,
            "identical_retry_denied": unknown,
        }
        if error:
            raise BioenhancerNativePartialResultError(str(error), partial_result=result) from error
        return result


class GuardedCampaignRunner:
    stage = "1-15-9"

    def __init__(self, stop):
        self.stop = stop
        self.ap_current = 20
        self.observations = []
        self.calls = []
        self.inputs = []
        self.admission_override = None
        self.on_entry = None
        self.on_input = None
        self.check_runtime_owner = None
        self.fault = None
        self.partial_after_wins = 0
        self.regenerated_ap = 0
        self.battle_seconds = 0
        self.actions = self.effects = 0

    def observe_home_ap(self, identity, checkpoint):
        raise AssertionError("preclaim game observation forbidden")

    def __call__(self, identity, previous_reset, checkpoint):
        checkpoint()
        self.calls.append((identity, previous_reset))
        self.observations.append(identity)
        if self.on_entry:
            self.on_entry()
        checkpoint()
        if self.check_runtime_owner:
            self.check_runtime_owner()
        before = self.ap_current
        consumed = 0
        entries = battles = wins = regenerated = 0
        error = None
        try:
            while self.ap_current >= 14:
                checkpoint()
                entries += 1
                self.actions += 1
                pending = self.fault == "partial" and wins == self.partial_after_wins
                for index in range(2 if pending else 6):
                    checkpoint()
                    self.inputs.append((identity.reset_id, entries, index))
                    consumed += 1
                    if self.on_input:
                        self.on_input(index)
                if pending:
                    break
                battles += 1
                if self.fault == "unknown":
                    break
                self.ap_current -= 14
                wins += 1
                self.effects += 1
                self.stop.now += self.battle_seconds
                if wins == 1:
                    self.ap_current += self.regenerated_ap
                    regenerated = self.regenerated_ap
                if self.fault == "canary":
                    break
        except Exception as exc:
            error = exc
        failed = self.fault in {"partial", "unknown"} or error is not None
        result = {
            "status": "unresolved" if failed else "completed" if wins else "deferred",
            "destination": self.stage, "ap_cost": 14,
            "ap_before": before, "ap_after": self.ap_current,
            "progress": {"initial_ap": before, "current_ap": self.ap_current,
                         "ap_spent": 14 * wins, "completed_runs": wins,
                         "ap_regenerated": regenerated, "loss_seen": False},
            "battle_outcome": "victory" if wins else None,
            "result_successor_verified": not failed and bool(wins),
            "terminal_home_verified": not failed,
            "stage_entry_transport_count": entries,
            "new_battle_count": battles,
            "committed_ap_effect_count": wins,
            "campaign_dispatch_count": entries, "total_input_count": consumed,
            "accounting_verified": True,
            "effect_reconciliation_required": failed, "identical_retry_denied": failed,
            "time_basis": "utc", "completed_at_utc": self.stop.now,
            "cadence_seconds": 300.0, "next_eligible_at": self.stop.now + 300.0,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "task_id": identity.task_id,
            "runtime_profile_id": CAMPAIGN_PROFILE_ID,
        }
        if error is not None:
            raise CampaignApRunnerError(str(error), result) from error
        if self.fault == "partial":
            raise CampaignApRunnerError("native successor lost after Stage dispatch", result)
        return result


class GuardedNovaRunner:
    def __init__(self, stop):
        self.stop = stop
        self.calls = []
        self.inputs = []
        self.remaining = 2
        self.reset_id = None
        self.on_input = self.on_entry = None
        self.uncertain = False
        self.actions = 0

    @property
    def effects(self):
        return self.actions

    def __call__(self, identity, previous_reset, checkpoint):
        checkpoint()
        if self.reset_id != identity.reset_id:
            self.remaining = 2
            self.reset_id = identity.reset_id
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry()
        before = self.remaining
        consumed = 0
        praise = 0
        try:
            for index in range(4):
                checkpoint()
                self.inputs.append((identity.reset_id, index))
                consumed += 1
                if index == 2:
                    praise = 1
                    self.actions += 1
                    self.remaining -= 1
                if self.on_input:
                    self.on_input(index)
        except ServiceError:
            self.uncertain = True
        now = self.stop.now
        return {
            "status": "unresolved" if self.uncertain else "completed",
            "terminal_home_verified": not self.uncertain,
            "time_basis": "utc", "completed_at_utc": now,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id, "attempts_before": before,
            "attempts_after": self.remaining, "praise_transport_calls": praise,
            "total_input_count": consumed, "journal_status": "confirmed" if praise else None,
            "cooldown_seconds": 300 if self.remaining else None,
            "next_eligible_at": now + 300 if self.remaining else None,
        }



class GuardedRecruitmentRunner:
    """Service-level stand-in; the real controller is exercised by test_service_recruitment."""

    def __init__(self, stop):
        self.stop = stop
        self.calls, self.inputs = [], []
        self.uncertain = False
        self.actions = 0
        self.on_input = self.on_entry = None

    @property
    def effects(self):
        return self.actions

    def __call__(self, identity, previous_reset, checkpoint):
        checkpoint()
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry()
        consumed = actions = 0
        try:
            for index in range(4):
                checkpoint()
                self.inputs.append((identity.reset_id, index))
                consumed += 1
                if index == 2:
                    actions = 1
                    self.actions += 1
                if self.on_input:
                    self.on_input(index)
        except ServiceError:
            self.uncertain = True
        return {
            "status": "unresolved" if self.uncertain else "completed",
            "terminal_home_verified": not self.uncertain,
            "time_basis": "utc", "completed_at_utc": self.stop.now,
            "account_id": identity.account_id, "server_id": identity.server_id,
            "reset_id": identity.reset_id,
            "maintenance_state": json.loads(NoahMaintenanceState.for_identity(identity).to_json()),
            "total_input_count": consumed, "recruitment_dispatch_count": actions,
            "actions_completed": actions,
        }
