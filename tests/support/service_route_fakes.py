"""Guarded native-runner fakes shared by the service route contract and route dispatch modules.

Each fake models one route's native runner contract: it checkpoints before every input,
counts inputs and resource actions, and returns (or raises) the same result shapes the
real runner produces.  No fake touches a device; all hooks are optional.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    ALLIANCE_HELP_FLOW_ID, ALLIANCE_HELP_MAX_INPUTS, ALLIANCE_HELP_PRODUCT_ID,
    ALLIANCE_HELP_PRODUCT_REVISION,
    BIOENHANCER_FLOW_ID, CAMPAIGN_PROFILE_ID, DAILY_REWARDS_FLOW_ID,
    DAILY_REWARDS_PROFILE_ID, DAILY_REWARDS_PRODUCT_ID, DAILY_REWARDS_PRODUCT_REVISION,
    ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID, RESOURCE_ITEM_FLOW_ID,
    RESOURCE_ITEM_MAX_INPUTS, RESOURCE_ITEM_PRODUCT_ID, RESOURCE_ITEM_PRODUCT_REVISION,
    RECRUITMENT_FLOW_ID, RUINS_FLOW_ID, RUINS_PRODUCT_ID, RUINS_PRODUCT_REVISION,
    SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID,
)

from tasks.alliance_help import (
    CONSEQUENCE as ALLIANCE_HELP_CONSEQUENCE, DAILY_REQUEST_LIMIT,
    INDIVIDUAL_TARGET_IDENTITY, POSTCONDITION as ALLIANCE_HELP_POSTCONDITION,
    SEMANTIC_ACTION as ALLIANCE_HELP_SEMANTIC_ACTION,
    SOURCE_STATE as ALLIANCE_HELP_SOURCE_STATE, alliance_help_action_key,
)
from tasks.ruins_challenge import KNOWN_CHALLENGE_IDENTITIES
from automation_service.service import ServiceError
from automation_service.supply import (
    PRODUCT_ID as SUPPLY_PRODUCT_ID, PRODUCT_REVISION as SUPPLY_PRODUCT_REVISION,
    SupplyNativePartialResultError,
)
from automation_service.ultimate import (
    PRODUCT_ID as ULTIMATE_PRODUCT_ID, PROFILE_ID as ULTIMATE_PROFILE_ID, UltimateRunnerError,
)
from scripts import navigation_development_boundary as boundary
from safe_action_core.resource_effect_authority import (
    ResourceEffectAuthority, ResourceOccurrenceIdentity,
)
from scripts.bioenhancer_free_research_route import parse_free_research_cooldown
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.noahs_tavern_recruit_maintenance import NoahMaintenanceState
from tasks.runtime_identity import (
    derive_resource_runtime_identity, derive_static_utc_reset, resource_fixed_runtime_binding,
)


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


class GuardedRoutePartialResultError(RuntimeError):
    def __init__(self, message, partial_result):
        super().__init__(message)
        self.partial_result = partial_result


class GuardedDailyRewardsRunner:
    MAX_ACTIONS = 6
    OBSERVATION_INTERVAL_SECONDS = 300

    def __init__(self, stop, root):
        self.stop = stop
        self.calls, self.inputs = [], []
        self.no_work = False
        self.aggregate_ready = True
        self.ready_chests = 0
        self.partial = False
        self.actions = 0
        self.on_entry = self.on_input = None
        self.directory = root / "daily-native-fake"
        self.directory.mkdir()
        home_bytes = b"offline-fake-home-frame"
        (self.directory / "current-home.png").write_bytes(home_bytes)
        self.home_sha = hashlib.sha256(home_bytes).hexdigest()
        self.chest_keys = [f"daily-chest-{value}" for value in (30, 60, 90, 120, 150)]

    @property
    def effects(self):
        return self.actions

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock, occurrence_key):
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry()

        claims = []
        if not self.no_work and self.aggregate_ready:
            claims.append("aggregate_claim")
        if not self.no_work:
            claims.extend(["milestone_chest"] * max(
                0, min(self.ready_chests, 5),
            ))
        plan = ["open_quest", "select_daily", *claims, "return_home"]
        count = dispatched = committed = chest_count = 0
        aggregate_claimed = False
        error = None
        try:
            for index, label in enumerate(plan):
                checkpoint()
                self.inputs.append((identity.reset_id, index, label))
                count += 1
                consequential = label in {"aggregate_claim", "milestone_chest"}
                if consequential:
                    dispatched += 1
                    self.actions += 1
                    if self.partial:
                        raise RuntimeError("Daily claim successor lost after dispatch")
                    committed += 1
                    if label == "aggregate_claim":
                        aggregate_claimed = True
                    else:
                        chest_count += 1
                if self.on_input:
                    self.on_input(index)
        except Exception as exc:
            error = exc

        now = self.stop.now
        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(), datetime.fromtimestamp(now, timezone.utc),
        )
        backend_mapping = asdict(backend)
        backend_mapping["assurance"] = backend.assurance.value
        backend_mapping["evidence_refs"] = list(backend.evidence_refs)
        result = {
            "status": "unresolved" if error else "completed",
            "flow_id": DAILY_REWARDS_FLOW_ID,
            "product_id": DAILY_REWARDS_PRODUCT_ID,
            "product_revision": DAILY_REWARDS_PRODUCT_REVISION,
            "task_id": DAILY_REWARDS_PRODUCT_ID,
            "account_id": identity.account_id,
            "server_id": identity.server_id,
            "reset_id": identity.reset_id,
            "occurrence_key": occurrence_key,
            "time_basis": "utc",
            "runtime_profile_id": DAILY_REWARDS_PROFILE_ID,
            "native_session_directory": str(self.directory),
            "backend_identity": backend_mapping,
            "completed_at_utc": now,
            "observation_interval_seconds": self.OBSERVATION_INTERVAL_SECONDS,
            "next_due_at_utc": now + self.OBSERVATION_INTERVAL_SECONDS,
            "input_count": count,
            "total_input_count": count,
            "total_action_count": dispatched,
            "reward_claim_transport_calls": dispatched,
            "committed_action_count": committed,
            "accounting_verified": True,
            "no_work": self.no_work or not claims,
            "no_work_evidence": (
                {
                    "selected_daily": True,
                    "reset_id": identity.reset_id,
                    "source_frame_sha256": "a" * 64,
                    "ordinary_claim_controls": 0,
                    "ready_chest_count": 0,
                    "static_or_locked_chest_keys": self.chest_keys,
                }
                if self.no_work or not claims else None
            ),
            "aggregate_claim": {
                "status": (
                    "unresolved" if error and "aggregate_claim" in claims and dispatched
                    else "confirmed" if aggregate_claimed else "none"
                ),
                "dispatch_count": int("aggregate_claim" in claims and dispatched > 0),
                "confirmed": aggregate_claimed,
                "reset_id": identity.reset_id,
                "ready_batch_proven": aggregate_claimed,
                "free_only": True,
                "control_identity": "daily-quest-claim",
                "ordinary_claim_controls_cleared": aggregate_claimed,
                **(
                    {
                        "batch_identity": occurrence_key,
                        "successor_frame_sha256": "c" * 64 if aggregate_claimed else None,
                    }
                    if "aggregate_claim" in claims and dispatched > 0 else {}
                ),
                "source_frame_sha256": "b" * 64,
            },
            "chests_collected": [
                {
                    "milestone_key": self.chest_keys[index],
                    "status": "confirmed",
                    "successor_state": "claimed",
                    "reset_id": identity.reset_id,
                    "target_identity": "activity-milestone-chest",
                    "control_class": "MILESTONE_CHEST",
                    "ready_state_proven": True,
                    "free_only": True,
                    "cost_type": "none",
                    "successor_milestone_key": self.chest_keys[index],
                    "source_frame_sha256": "d" * 64,
                    "successor_frame_sha256": "e" * 64,
                }
                for index in range(chest_count)
            ],
            "milestone_scan": {
                "status": "verified",
                "selected_daily": True,
                "reset_id": identity.reset_id,
                "source_frame_sha256": "a" * 64,
                "ready_chest_count": chest_count,
                "ready_chest_keys": self.chest_keys[:chest_count],
                "static_or_locked_chest_keys": self.chest_keys[chest_count:],
            },
            "unclaimed_ready_chest_count": 0,
            "observed_points": None,
            "terminal_home_verified": error is None,
            "terminal_home_frame": (
                {"frame_path": "current-home.png", "frame_sha256": self.home_sha}
                if error is None else None
            ),
            "effect_reconciliation_required": error is not None and dispatched > 0,
            "identical_retry_denied": error is not None or committed > 0,
        }
        if error:
            raise GuardedRoutePartialResultError(str(error), result) from error
        return result


class GuardedResourceItemRunner:
    def __init__(self, stop):
        self.stop = stop
        self.calls, self.inputs = [], []
        self.partial = False
        self.actions = 0
        self.on_entry = self.on_input = None

    @property
    def effects(self):
        return self.actions

    def __call__(self, identity, previous_reset, checkpoint, *, runtime_input_lock, occurrence_key):
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        self.calls.append((identity, previous_reset))
        if self.on_entry:
            self.on_entry()

        plan = ("open_inventory", "identify_1k_food", "use_one_item", "return_home")
        count = dispatched = 0
        error = None
        try:
            for index, label in enumerate(plan):
                checkpoint()
                self.inputs.append((identity.reset_id, index, label))
                count += 1
                if label == "use_one_item":
                    dispatched += 1
                    self.actions += 1
                    if self.partial:
                        raise RuntimeError("resource item successor lost after dispatch")
                if self.on_input:
                    self.on_input(index)
        except Exception as exc:
            error = exc

        resource_day_start = datetime.fromtimestamp(
            self.stop.now, timezone.utc,
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        resource_deadline = resource_day_start + timedelta(days=1)
        resource_reset_identity_id = (
            f"reset-deadline:{resource_deadline.isoformat().replace('+00:00', 'Z')}"
        )
        resource_identity = ResourceOccurrenceIdentity(
            account_id=identity.account_id,
            server_id=identity.server_id,
            flow_id=RESOURCE_ITEM_FLOW_ID,
            reset_identity_id=resource_reset_identity_id,
        )
        resource_context = resource_identity.authorization_context()
        resource_occurrence_key = resource_identity.occurrence_key()
        resource_occurrence_id = resource_identity.occurrence_id()
        action_key = ResourceEffectAuthority.resource_action_key(resource_context, 1)
        reservation_id = ResourceEffectAuthority.resource_reservation_id(resource_context, 1)
        fixture_digest = hashlib.sha256(
            resource_occurrence_key.encode("utf-8"),
        ).hexdigest()
        action_id = f"resource-action:v1:{fixture_digest}"
        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(), datetime.fromtimestamp(self.stop.now, timezone.utc),
        )
        window = derive_static_utc_reset(datetime.fromtimestamp(self.stop.now, timezone.utc))
        before_frame = {"path": "frames/item-before.png", "sha256": "1" * 64}
        after_frame = {"path": "frames/item-after.png", "sha256": "2" * 64}
        home_frame = {"path": "frames/current-home.png", "sha256": "3" * 64}
        result = {
            "status": "unresolved" if error else "complete_for_reset",
            "flow_id": RESOURCE_ITEM_FLOW_ID,
            "product_id": RESOURCE_ITEM_PRODUCT_ID,
            "product_revision": RESOURCE_ITEM_PRODUCT_REVISION,
            "task_id": RESOURCE_ITEM_PRODUCT_ID,
            "account_id": identity.account_id,
            "server_id": identity.server_id,
            "reset_id": identity.reset_id,
            "occurrence_key": occurrence_key,
            "time_basis": "utc",
            "completed_at_utc": self.stop.now,
            "input_count": count,
            "total_input_count": count,
            "max_inputs": RESOURCE_ITEM_MAX_INPUTS,
            "max_actions": 1,
            "session_input_count": count,
            "runtime_input_count": count,
            "action_count": dispatched,
            "resource_account_id": backend.account_id,
            "resource_server_id": backend.server_id,
            "resource_runtime_scope": backend.runtime_scope,
            "resource_identity_assurance": backend.assurance.value,
            "resource_backend_identity_reset_id": backend.reset_id,
            "resource_reset_start_utc": window.reset_start_text,
            "resource_reset_deadline_utc": window.reset_deadline_text,
            "action_game_day_id": backend.reset_id,
            "action_task_id": RESOURCE_ITEM_FLOW_ID,
            "action_semantic_action": "USE_RESOURCE_ITEM",
            "action_source_state": "RESOURCES_1K_FOOD_READY",
            "action_target_identity": "daily-resource-item:use-1k-food",
            "action_expected_postcondition": "RESOURCES_1K_FOOD_USED",
            "action_consequence": "ordinary_non_idempotent_resource_item_use",
            "action_cost_type": "owned_inventory_item",
            "action_cost_amount": 1,
            "action_quantity": 1,
            "item_use_transport_calls": dispatched,
            "committed_action_count": int(dispatched > 0 and error is None),
            "accounting_verified": True,
            "journal_status": (
                "unresolved" if error and dispatched else "confirmed" if dispatched else None
            ),
            "resource_delta_verified": error is None and dispatched > 0,
            "terminal_home_verified": error is None,
            "effect_reconciliation_required": error is not None and dispatched > 0,
            "identical_retry_denied": error is not None,
            "action_id": action_id,
            "action_key": action_key,
            "resource_action_id": action_id,
            "resource_action_key": action_key,
            "resource_attempt_id": f"attempt:v1:{fixture_digest}",
            "resource_reset_identity_id": resource_reset_identity_id,
            "resource_occurrence_key": resource_occurrence_key,
            "resource_occurrence_id": resource_occurrence_id,
            "reservation_id": reservation_id,
            "resource_effect_state": (
                "UNRESOLVED" if error and dispatched else "CONFIRMED" if dispatched else None
            ),
            "reservation_state": (
                "UNRESOLVED" if error and dispatched else "EFFECT_CONFIRMED" if dispatched else None
            ),
            "terminal_observation_state": (
                "HOME_CANONICAL" if error is None else "UNRESOLVED" if dispatched else None
            ),
            "before_owned_quantity": 2 if dispatched else None,
            "after_owned_quantity": 1 if dispatched and error is None else None,
            "owned_item_decrement": 1 if dispatched and error is None else None,
            "terminal_home_frame": (
                home_frame
                if error is None else None
            ),
            "semantic_evidence": {
                "item_before_frame": before_frame,
                "item_after_frame": after_frame,
                "terminal_home_frame": home_frame,
            },
            "next_eligible_at_utc": resource_deadline.timestamp(),
        }
        if error:
            raise GuardedRoutePartialResultError(str(error), result) from error
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
    """Checkpoint every iteration and retain partial counts on checkpoint failure.

    Unlike the original local fake, wrap checkpoint failures as
    CampaignApRunnerError with a partial result, matching
    automation_service/campaign.py's claimed-run partial-result boundary.
    This is the deliberate third difference, alongside uniform hooks and counters.
    """

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


class GuardedRuinsRunner:
    """Service-manager fake with a dispatched-but-unresolved challenge outcome."""

    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs, self.occurrence_keys = [], [], []
        self.partial = False
        self.actions = 0
        self.on_input = self.on_entry = None

    @property
    def effects(self):
        return self.actions

    def __call__(self, identity, previous_reset, checkpoint, *,
                 runtime_input_lock, occurrence_key):
        checkpoint()
        runtime_input_lock.assert_held(
            runtime_input_lock.owner, runtime_input_lock.invocation_id,
        )
        self.calls.append((identity, previous_reset))
        self.occurrence_keys.append(occurrence_key)
        if self.on_entry:
            self.on_entry()

        plan = (
            "open_home_atlas", "open_ruins", "open_challenge", "dispatch_npc",
            "open_overview", "inspect_ready_chest", "claim_ready_chest", "return_home",
        )
        count = challenge_calls = chest_calls = 0
        error = None
        try:
            for index, label in enumerate(plan):
                checkpoint()
                self.inputs.append((identity.reset_id, index, label))
                count += 1
                if label == "dispatch_npc":
                    challenge_calls += 1
                    self.actions += 1
                    if self.partial:
                        raise RuntimeError("Ruins challenge result lost after dispatch")
                elif label == "claim_ready_chest":
                    chest_calls += 1
                    self.actions += 1
                if self.on_input:
                    self.on_input(index)
        except Exception as exc:
            error = exc

        total = challenge_calls + chest_calls
        coverage = {item: "already claimed" for item in KNOWN_CHALLENGE_IDENTITIES}
        claims = []
        if chest_calls:
            identity_key = KNOWN_CHALLENGE_IDENTITIES[0]
            coverage[identity_key] = "newly claimed"
            claims.append({"identity": identity_key, "ruins_medals": 55})
        unresolved = error is not None
        result = {
            "status": "unresolved" if unresolved and total else "blocked" if unresolved else "completed",
            "flow_id": RUINS_FLOW_ID,
            "product_id": RUINS_PRODUCT_ID,
            "product_revision": RUINS_PRODUCT_REVISION,
            "task_id": RUINS_PRODUCT_ID,
            "account_id": identity.account_id,
            "server_id": identity.server_id,
            "reset_id": identity.reset_id,
            "occurrence_key": occurrence_key,
            "time_basis": "utc",
            "completed_at_utc": self.stop.now,
            "input_count": count,
            "total_input_count": count,
            "action_count": total,
            "actions_completed": total,
            "ruins_dispatch_count": total,
            "challenge_transport_calls": challenge_calls,
            "chest_claim_transport_calls": chest_calls,
            "challenge_participation_confirmed": challenge_calls == 1 and not unresolved,
            "daily_action_ready": challenge_calls == 1 and not unresolved,
            "challenge_status": "unresolved" if unresolved and challenge_calls else "confirmed",
            "challenge_result": "failure" if challenge_calls and not unresolved else None,
            "challenge_identity": "Nova Challenge" if challenge_calls and not unresolved else None,
            "chest_coverage": coverage,
            "newly_claimed_chests": claims,
            "resource_delta": sum(item["ruins_medals"] for item in claims),
            "accounting_verified": True,
            "terminal_home_verified": not unresolved,
            "effect_reconciliation_required": unresolved and total > 0,
            "identical_retry_denied": unresolved,
        }
        if error:
            raise GuardedRoutePartialResultError(str(error), result) from error
        return result


class GuardedAllianceHelpRunner:
    """Guarded ten-request service fake retaining a confirmed prefix on ambiguity."""

    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs, self.occurrence_keys = [], [], []
        self.partial = False
        self.actions = 0
        self.on_input = self.on_entry = None

    @property
    def effects(self):
        return self.actions

    def __call__(self, identity, previous_reset, checkpoint, *,
                 runtime_input_lock, occurrence_key):
        checkpoint()
        runtime_input_lock.assert_held(
            runtime_input_lock.owner, runtime_input_lock.invocation_id,
        )
        self.calls.append((identity, previous_reset))
        self.occurrence_keys.append(occurrence_key)
        if self.on_entry:
            self.on_entry()

        plan = (
            "open_alliance", "open_speedup_help",
            *("help_request",) * DAILY_REQUEST_LIMIT,
            *("verify_request",) * (ALLIANCE_HELP_MAX_INPUTS - 2 - DAILY_REQUEST_LIMIT),
        )
        input_count = calls = 0
        error = None
        try:
            for index, label in enumerate(plan):
                checkpoint()
                self.inputs.append((identity.reset_id, index, label))
                input_count += 1
                if label == "help_request":
                    calls += 1
                    self.actions += 1
                    if self.partial and calls == 3:
                        raise RuntimeError("Alliance Help request result unresolved after transport")
                if self.on_input:
                    self.on_input(index)
        except Exception as exc:
            error = exc

        backend = derive_resource_runtime_identity(
            resource_fixed_runtime_binding(),
            datetime.fromtimestamp(self.stop.now, timezone.utc),
        )
        confirmed = max(0, calls - 1) if self.partial and error else calls
        result = self._result(
            identity, backend, occurrence_key, input_count, calls, confirmed,
            error=error,
        )
        if error:
            raise GuardedRoutePartialResultError(str(error), result) from error
        return result

    def _result(self, identity, backend, occurrence_key, input_count, calls,
                confirmed, *, error=None):
        proof = {
            "runtime_scope": backend.runtime_scope,
            "account_id": backend.account_id,
            "server_id": backend.server_id,
            "reset_id": backend.reset_id,
            "assurance": backend.assurance.value,
            "evidence_refs": list(backend.evidence_refs),
            "observed_utc": backend.observed_utc,
            "expires_utc": backend.expires_utc,
            "runtime_binding_digest": backend.runtime_binding_digest,
            "reset_start_utc": backend.reset_start_utc,
            "reset_deadline_utc": backend.reset_deadline_utc,
        }
        records, actions, dispatches = [], [], []
        for ordinal in range(1, calls + 1):
            key = alliance_help_action_key(
                runtime_scope=backend.runtime_scope,
                account_id=identity.account_id,
                server_id=identity.server_id,
                reset_id=backend.reset_id,
                ordinal=ordinal,
            )
            immediate_sha = hashlib.sha256(f"immediate-{ordinal}".encode()).hexdigest()
            selected_sha = hashlib.sha256(f"selected-{ordinal}".encode()).hexdigest()
            if ordinal <= confirmed:
                records.append({
                    "action_id": f"fixture-action-{ordinal}",
                    "action_key": key,
                    "request_ordinal": ordinal,
                    "task_id": ALLIANCE_HELP_FLOW_ID,
                    "semantic_action": ALLIANCE_HELP_SEMANTIC_ACTION,
                    "source_state": ALLIANCE_HELP_SOURCE_STATE,
                    "target_identity": INDIVIDUAL_TARGET_IDENTITY,
                    "game_day_id": backend.reset_id,
                    "expected_postcondition": ALLIANCE_HELP_POSTCONDITION,
                    "consequence": ALLIANCE_HELP_CONSEQUENCE,
                    "cost_type": "none",
                    "cost_amount": 0,
                    "quantity": 1,
                    "consequential": 1,
                    "final_status": "confirmed",
                })
                actions.append({
                    "status": "confirmed",
                    "request_ordinal": ordinal,
                    "action_key": key,
                    "journal_status": "confirmed",
                    "verified_request_count": 1,
                    "help_transport_calls": 1,
                    "effect_reconciliation_required": False,
                    "selected_request_sha256": selected_sha,
                    "immediate_before_frame": {
                        "frame_path": f"immediate-{ordinal}.png",
                        "frame_sha256": immediate_sha,
                    },
                    "immediate_before_sha256": immediate_sha,
                    "immediate_daily_alliance_coin_balance": (ordinal - 1) * 1000,
                    "immediate_daily_alliance_coin_limit": 50000,
                    "request_result_evidence": [
                        {
                            "selected_request_absent": True,
                            "screen_state": ALLIANCE_HELP_SOURCE_STATE,
                            "source_fresh": True,
                            "overlay_clear": True,
                            "success_message": True,
                            "daily_alliance_coin_balance": ordinal * 1000,
                            "daily_alliance_coin_limit": 50000,
                        },
                        {
                            "selected_request_absent": True,
                            "screen_state": ALLIANCE_HELP_SOURCE_STATE,
                            "source_fresh": True,
                            "overlay_clear": True,
                            "success_message": False,
                            "daily_alliance_coin_balance": ordinal * 1000,
                            "daily_alliance_coin_limit": 50000,
                        },
                    ],
                })
            else:
                actions.append({
                    "status": "reconciliation_required",
                    "request_ordinal": ordinal,
                    "action_key": key,
                    "journal_status": "unresolved",
                    "verified_request_count": 0,
                    "help_transport_calls": 1,
                    "effect_reconciliation_required": True,
                })
            dispatches.append({
                "immediate_before_sha256": immediate_sha,
                "target_identity": INDIVIDUAL_TARGET_IDENTITY,
                "action_key": key,
            })
        return {
            "status": (
                "reconciliation_required" if error and calls
                else "blocked" if error
                else "complete_for_reset"
            ),
            "reason": "help_request_result_unresolved" if error else "ten_free_requests_confirmed",
            "flow_id": ALLIANCE_HELP_FLOW_ID,
            "product_id": ALLIANCE_HELP_PRODUCT_ID,
            "product_revision": ALLIANCE_HELP_PRODUCT_REVISION,
            "task_id": ALLIANCE_HELP_PRODUCT_ID,
            "account_id": identity.account_id,
            "server_id": identity.server_id,
            "reset_id": identity.reset_id,
            "scheduler_reset_id": identity.reset_id,
            "backend_reset_id": backend.reset_id,
            "occurrence_key": occurrence_key,
            "time_basis": "utc",
            "completed_at_utc": self.stop.now,
            "backend_identity": proof,
            "confirmed_request_count": confirmed,
            "confirmed_request_records": records,
            "committed_action_count": confirmed,
            "verified_request_count": confirmed,
            "help_transport_calls": calls,
            "request_actions": actions,
            "help_dispatch_evidence": dispatches,
            "remaining_request_target": DAILY_REQUEST_LIMIT - confirmed,
            "max_inputs": ALLIANCE_HELP_MAX_INPUTS,
            "max_actions": DAILY_REQUEST_LIMIT,
            "input_count": input_count,
            "total_input_count": input_count,
            "session_input_count": input_count,
            "runtime_input_count": input_count,
            "native_input_count": input_count,
            "native_execution_verified": error is None,
            "native_failure": None if error is None else str(error),
            "accounting_verified": True,
            "effect_reconciliation_required": bool(error and calls),
            "identical_retry_denied": bool(error),
            "no_work": False,
            "no_work_evidence": None,
            "terminal_home_verified": error is None,
            "terminal_home_frame": (
                {"frame_path": "alliance-help-home.png", "frame_sha256": "f" * 64}
                if error is None else None
            ),
        }
