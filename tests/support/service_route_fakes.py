"""Guarded native-runner fakes shared by the service route contract and route dispatch modules.

Each fake models one route's native runner contract: it checkpoints before every input,
counts inputs and resource actions, and returns (or raises) the same result shapes the
real runner produces.  No fake touches a device; all hooks are optional.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import asdict, replace
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
    ALLIANCE_DONATION_FLOW_ID, ALLIANCE_DONATION_MAX_INPUTS,
    ALLIANCE_DONATION_PRODUCT_ID, ALLIANCE_DONATION_PRODUCT_REVISION,
    ALLIANCE_DONATION_PROFILE_ID, ALLIANCE_HELP_FLOW_ID, ALLIANCE_HELP_MAX_INPUTS,
    ALLIANCE_HELP_PRODUCT_ID, ALLIANCE_HELP_PRODUCT_REVISION,
    ALLIANCE_SHOP_FLOW_ID, ALLIANCE_SHOP_MAX_INPUTS, ALLIANCE_SHOP_PRODUCT_ID,
    ALLIANCE_SHOP_PRODUCT_REVISION, ALLIANCE_SHOP_PROFILE_ID, BIOENHANCER_FLOW_ID,
    CAMPAIGN_PROFILE_ID, DAILY_REWARDS_FLOW_ID, DAILY_REWARDS_PROFILE_ID,
    DAILY_REWARDS_PRODUCT_ID, DAILY_REWARDS_PRODUCT_REVISION, DAILY_SHOPS_FLOW_ID,
    DAILY_SHOPS_MAX_INPUTS, DAILY_SHOPS_PRODUCT_ID, DAILY_SHOPS_PRODUCT_REVISION,
    DAILY_SHOPS_PROFILE_ID, ENHANCEMENT_FLOW_ID, PERSONAL_MIGHT_FLOW_ID,
    NANO_MATERIAL_PRODUCTION_FLOW_ID, NANO_MATERIAL_PRODUCTION_MAX_INPUTS,
    NANO_MATERIAL_PRODUCTION_PRODUCT_ID, NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION,
    NANO_MATERIAL_PRODUCTION_PROFILE_ID, NANOWEAPON_FLOW_ID, NANOWEAPON_MAX_INPUTS,
    NANOWEAPON_PRODUCT_ID, NANOWEAPON_PRODUCT_REVISION, NANOWEAPON_PROFILE_ID,
    RESOURCE_ITEM_FLOW_ID, RESOURCE_ITEM_MAX_INPUTS, RESOURCE_ITEM_PRODUCT_ID,
    RESOURCE_ITEM_PRODUCT_REVISION, RECRUITMENT_FLOW_ID, RUINS_FLOW_ID,
    RUINS_PRODUCT_ID, RUINS_PRODUCT_REVISION, SUPPLY_FLOW_ID, ULTIMATE_FLOW_ID,
    HALL_OF_WAR_FLOW_ID, HALL_OF_WAR_PRODUCT_ID,
    HALL_OF_WAR_PRODUCT_REVISION, HALL_OF_WAR_PROFILE_ID,
    TROOP_TRAINING_FLOW_ID, TROOP_TRAINING_PRODUCT_ID,
    TROOP_TRAINING_PRODUCT_REVISION, TROOP_TRAINING_PROFILE_ID,
)
from tasks.purchases_disabled import (
    ALLIANCE_CURRENCY, ALLIANCE_FALLBACK_ITEM, ALLIANCE_OTHER_SHOP,
    ALLIANCE_WEEKLY_SHOP, RARE_EARTH_CURRENCY, RARE_EARTH_MODULE_ITEM,
    RARE_EARTH_SHOP, RUINS_CHIP_ITEM, RUINS_CURRENCY, RUINS_SHOP,
    ALLIANCE_WEEKLY_ITEMS, ShopOffer, alliance_shop_choice,
    canonical_purchase_action_key,
)
from tasks.nano_material_production import (
    NANO_MATERIAL_PRODUCTION_DURATION_SECONDS, NANO_MATERIAL_PRODUCTION_TARGET,
)
from tasks.nanoweapon import NANO_PARTS_REQUIRED, NORMAL_CRAFT_DURATION_SECONDS
from tasks.scheduler_task_result import SchedulerIdentity
from automation_service.hero_duel import (
    FLOW_ID as HERO_DUEL_FLOW_ID,
    MAX_ACTIONS as HERO_DUEL_MAX_ACTIONS,
    MAX_INPUTS as HERO_DUEL_MAX_INPUTS,
    PROFILE_ID as HERO_DUEL_PROFILE_ID,
    PRODUCT_ID as HERO_DUEL_PRODUCT_ID,
    PRODUCT_REVISION as HERO_DUEL_PRODUCT_REVISION,
    HeroDuelRunner,
)
from automation_service.recommended_research import (
    FLOW_ID as RECOMMENDED_RESEARCH_FLOW_ID,
    MAX_ACTIONS as RECOMMENDED_RESEARCH_MAX_ACTIONS,
    PROFILE_ID as RECOMMENDED_RESEARCH_PROFILE_ID,
    MAX_INPUTS as RECOMMENDED_RESEARCH_MAX_INPUTS,
    PRODUCT_ID as RECOMMENDED_RESEARCH_PRODUCT_ID,
    PRODUCT_REVISION as RECOMMENDED_RESEARCH_PRODUCT_REVISION,
    RecommendedResearchRunner,
)
from automation_service.food_farm_boost import (
    FLOW_ID as FOOD_FARM_BOOST_FLOW_ID,
    MAX_ACTIONS as FOOD_FARM_BOOST_MAX_ACTIONS,
    MAX_INPUTS as FOOD_FARM_BOOST_MAX_INPUTS,
    PROFILE_ID as FOOD_FARM_BOOST_PROFILE_ID,
    PRODUCT_ID as FOOD_FARM_BOOST_PRODUCT_ID,
    PRODUCT_REVISION as FOOD_FARM_BOOST_PRODUCT_REVISION,
    FoodFarmBoostRunner,
)
from automation_service.hall_of_war import (
    FLOW_ID as HALL_OF_WAR_ADAPTER_FLOW_ID,
    MAX_ACTIONS as HALL_OF_WAR_MAX_ACTIONS,
    MAX_INPUTS as HALL_OF_WAR_ADAPTER_MAX_INPUTS,
    PROFILE_ID as HALL_OF_WAR_ADAPTER_PROFILE_ID,
    PRODUCT_ID as HALL_OF_WAR_ADAPTER_PRODUCT_ID,
    PRODUCT_REVISION as HALL_OF_WAR_ADAPTER_PRODUCT_REVISION,
    HallOfWarRunner,
)
from automation_service.troop_training import (
    FLOW_ID as TROOP_TRAINING_ADAPTER_FLOW_ID,
    MAX_ACTIONS as TROOP_TRAINING_MAX_ACTIONS,
    MAX_INPUTS as TROOP_TRAINING_ADAPTER_MAX_INPUTS,
    PROFILE_ID as TROOP_TRAINING_ADAPTER_PROFILE_ID,
    PRODUCT_ID as TROOP_TRAINING_ADAPTER_PRODUCT_ID,
    PRODUCT_REVISION as TROOP_TRAINING_ADAPTER_PRODUCT_REVISION,
    TroopTrainingRunner,
    make_training_start_action_key,
    training_identity_digest,
)
from automation_service.wali_upgrade import (
    FLOW_ID as WALI_UPGRADE_FLOW_ID,
    MAX_ACTIONS as WALI_UPGRADE_MAX_ACTIONS,
    MAX_INPUTS as WALI_UPGRADE_MAX_INPUTS,
    PROFILE_ID as WALI_UPGRADE_PROFILE_ID,
    PRODUCT_ID as WALI_UPGRADE_PRODUCT_ID,
    PRODUCT_REVISION as WALI_UPGRADE_PRODUCT_REVISION,
    WaliUpgradeRunner,
)
from tasks.hero_upgrade_disabled import HeroUpgradeObservation
from tasks.profile import BLUESTACKS_NATIVE_TARGET_PROVENANCE
from automation_service.native_execution import NativeRouteOutcome
from scripts import navigation_development_boundary as boundary
from safe_action_core.resource_effect_authority import (
    ResourceEffectAuthority, ResourceOccurrenceIdentity,
)
from scripts.bioenhancer_free_research_route import parse_free_research_cooldown
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.noahs_tavern_recruit_maintenance import NoahMaintenanceState
from tasks.hero_duel_disabled import hero_duel_action_key
from tasks.runtime_identity import FIXED_RUNTIME_SCOPE
from tasks.resource_boost_disabled import food_farm_boost_daily_action_key
from tasks.runtime_identity import (
    BLUESTACKS_SERIAL, derive_resource_runtime_identity, derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.troop_training import (
    FACILITY_BY_TYPE, TROOP_TYPES, ResourceReading, default_troop_training_config,
)
from tasks.alliance_help import (
    CONSEQUENCE as ALLIANCE_HELP_CONSEQUENCE, DAILY_REQUEST_LIMIT,
    INDIVIDUAL_TARGET_IDENTITY, POSTCONDITION as ALLIANCE_HELP_POSTCONDITION,
    SEMANTIC_ACTION as ALLIANCE_HELP_SEMANTIC_ACTION,
    SOURCE_STATE as ALLIANCE_HELP_SOURCE_STATE, alliance_help_action_key,
)
from tasks.ruins_challenge import KNOWN_CHALLENGE_IDENTITIES
from tests.support.service_stop import VirtualStop
from automation_service.service import ServiceError
from automation_service.supply import (
    PRODUCT_ID as SUPPLY_PRODUCT_ID, PRODUCT_REVISION as SUPPLY_PRODUCT_REVISION,
    SupplyNativePartialResultError,
)
from automation_service.ultimate import (
    PRODUCT_ID as ULTIMATE_PRODUCT_ID, PROFILE_ID as ULTIMATE_PROFILE_ID, UltimateRunnerError,
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
        self.challenge_results = ("failure",)
        self.challenge_paused = False
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
            "open_home_atlas", "open_ruins",
            *(label for _ in self.challenge_results for label in ("open_challenge", "dispatch_npc")),
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
        claims = []
        if chest_calls:
            identity_key = KNOWN_CHALLENGE_IDENTITIES[0]
            claims.append({"identity": identity_key})
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
            "challenge_participation_confirmed": bool(challenge_calls) and not unresolved,
            "daily_action_ready": bool(challenge_calls) and not unresolved,
            "challenge_status": (
                "unresolved" if unresolved and challenge_calls
                else "paused" if self.challenge_paused else "finished"
            ),
            "challenge_stages": (
                [{"identity": "Nova Challenge", "stage_cleared": stage, "stage_maximum": 20, "result": outcome}
                 for stage, outcome in enumerate(self.challenge_results[:challenge_calls])]
                if not unresolved else []
            ),
            "chest_status": "unresolved" if unresolved else "complete",
            "newly_claimed_chests": claims,
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
                    "operation_ordinal": ordinal,
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
                    "operation_ordinal": ordinal,
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
                    "request_result_evidence": [
                        {
                            "selected_request_absent": True,
                            "screen_state": ALLIANCE_HELP_SOURCE_STATE,
                            "source_fresh": True,
                            "overlay_clear": True,
                            "success_message": True,
                        },
                        {
                            "selected_request_absent": True,
                            "screen_state": ALLIANCE_HELP_SOURCE_STATE,
                            "source_fresh": True,
                            "overlay_clear": True,
                            "success_message": False,
                        },
                    ],
                })
            else:
                actions.append({
                    "status": "reconciliation_required",
                    "operation_ordinal": ordinal,
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


_C_EVIDENCE_SHA256 = "a" * 64


def _guarded_c_payload(
    *, flow_id, product_id, product_revision, profile_id, identity, previous_reset,
    occurrence_key, stop, started_at, input_count, max_inputs, max_actions,
    status, error=None, effect_unknown=False,
):
    """Build the fixed native Mapping envelope shared by the Batch C adapters."""
    backend = derive_resource_runtime_identity(
        resource_fixed_runtime_binding(),
        datetime.fromtimestamp(stop.now, timezone.utc),
    )
    backend_identity = {
        "runtime_scope": backend.runtime_scope,
        "account_id": backend.account_id,
        "server_id": backend.server_id,
        "backend_reset_id": backend.reset_id,
        "runtime_binding_digest": backend.runtime_binding_digest,
        "reset_start_utc": backend.reset_start_utc,
        "reset_deadline_utc": backend.reset_deadline_utc,
    }
    return {
        "status": status,
        "flow_id": flow_id,
        "product_id": product_id,
        "product_revision": product_revision,
        "task_id": product_id,
        "account_id": identity.account_id,
        "server_id": identity.server_id,
        "reset_id": identity.reset_id,
        "scheduler_reset_id": identity.reset_id,
        "previous_reset_id": previous_reset,
        "occurrence_key": occurrence_key,
        "runtime_profile_id": profile_id,
        "time_basis": "utc",
        "started_at_utc": started_at,
        "completed_at_utc": stop.now,
        "backend_identity": backend_identity,
        "input_count": input_count,
        "total_input_count": input_count,
        "session_input_count": input_count,
        "runtime_input_count": input_count,
        "max_inputs": max_inputs,
        "max_actions": max_actions,
        "native_execution_verified": error is None,
        "native_failure": None if error is None else str(error),
        "accounting_verified": True,
        "terminal_home_verified": error is None,
        "effect_reconciliation_required": effect_unknown,
        "identical_retry_denied": effect_unknown,
    }


class GuardedAllianceDonationRunner:
    """Mapping-shaped donation fake with attempted and confirmed ordinals kept separate."""

    ACTION_INPUTS = tuple(range(4, 14))

    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs, self.occurrence_keys = [], [], []
        self.confirmed_ordinals = []
        self.reset_id = None
        self.partial = False
        self.defer_after = None
        self.defer_reason = "no_attempts"
        self.on_input = self.on_entry = None
        self.last_result = None
        self.last_identity = None

    @property
    def effects(self):
        return len(self.confirmed_ordinals)

    def __call__(self, identity, previous_reset, checkpoint, *,
                 runtime_input_lock, occurrence_key):
        checkpoint()
        runtime_input_lock.assert_held(
            runtime_input_lock.owner, runtime_input_lock.invocation_id,
        )
        self.calls.append((identity, previous_reset))
        self.occurrence_keys.append(occurrence_key)
        if identity.reset_id != self.reset_id:
            self.reset_id = identity.reset_id
            self.confirmed_ordinals = []
        self.last_identity = identity
        if self.on_entry:
            self.on_entry()

        started = self.stop.now
        input_count = transport_calls = committed = 0
        error = None
        unknown = False
        deferred = False
        needed = 10 - len(self.confirmed_ordinals)
        try:
            for index in range(ALLIANCE_DONATION_MAX_INPUTS):
                checkpoint()
                self.inputs.append((identity.reset_id, index, "donation-route-input"))
                input_count += 1
                if index in self.ACTION_INPUTS and committed < needed:
                    transport_calls += 1
                    if self.partial and transport_calls == 3:
                        unknown = True
                        error = RuntimeError("donation successor is unknown after transport")
                        break
                    committed += 1
                    self.confirmed_ordinals.append(len(self.confirmed_ordinals) + 1)
                if self.on_input:
                    self.on_input(index)
                if self.defer_after is not None and committed >= self.defer_after:
                    deferred = True
                    break
        except Exception as exc:
            error = exc

        status = (
            "reconciliation_required" if unknown
            else "blocked" if error
            else "deferred" if deferred or len(self.confirmed_ordinals) < 10
            else "complete_for_reset"
        )
        result = _guarded_c_payload(
            flow_id=ALLIANCE_DONATION_FLOW_ID,
            product_id=ALLIANCE_DONATION_PRODUCT_ID,
            product_revision=ALLIANCE_DONATION_PRODUCT_REVISION,
            profile_id=ALLIANCE_DONATION_PROFILE_ID,
            identity=identity, previous_reset=previous_reset,
            occurrence_key=occurrence_key, stop=self.stop, started_at=started,
            input_count=input_count, max_inputs=ALLIANCE_DONATION_MAX_INPUTS,
            max_actions=10, status=status, error=error, effect_unknown=unknown,
        )
        result.update(
            terminal_status="completed" if error is None else status,
            donation_transport_calls=transport_calls,
            committed_action_count=committed,
            daily_committed_action_count=len(self.confirmed_ordinals),
            evidence_refs=("alliance-donation-home.png",),
            terminal_frame_sha256=_C_EVIDENCE_SHA256,
        )
        if deferred and error is None:
            observed = self.stop.now
            reason = self.defer_reason
            source = "observed_attempt_timer" if reason == "no_attempts" else "safe_resource_recheck"
            result.update(
                reason=reason,
                availability_evidence={
                    "tech_identity": "current automatic HOT target",
                    "game_day_id": identity.reset_id,
                    "source_frame_sha256": _C_EVIDENCE_SHA256,
                    "evidence_ref": "alliance-donation-availability.png",
                    "reason": reason,
                    "available_attempts": 0 if reason == "no_attempts" else 20,
                    "attempt_capacity": 20,
                    "observed_at_utc": observed,
                    "next_eligibility_source": source,
                    "next_attempt_available_in_seconds": 1800 if reason == "no_attempts" else None,
                    "cost_affordable": False if reason == "insufficient_resource" else None,
                    "donation_amount": 1000 if reason == "insufficient_resource" else None,
                },
                next_eligible_at=observed + (1800 if reason == "no_attempts" else 300),
            )
        self.last_result = result
        if error is not None:
            raise GuardedRoutePartialResultError(str(error), result) from error
        return result


class GuardedAllianceShopRunner:
    """Mapping-shaped one-purchase fake using the exact fallback result contract."""

    PURCHASE_INPUT = 12

    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs, self.occurrence_keys = [], [], []
        self.actions = 0
        self.partial = False
        self.on_input = self.on_entry = None
        self.selection_choice = None
        self.last_result = None
        self.last_identity = None

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
        self.last_identity = identity
        if self.on_entry:
            self.on_entry()

        started = self.stop.now
        weekly_offer = ShopOffer(
            shop_identity=ALLIANCE_WEEKLY_SHOP,
            item_identity=ALLIANCE_WEEKLY_ITEMS[0],
            currency_identity=ALLIANCE_CURRENCY,
            unit_price=1000, balance=0, stock=12, item_quantity=0,
            available=True, offer_identity="weekly:joy-coin",
        )
        fallback_offer = ShopOffer(
            shop_identity=ALLIANCE_OTHER_SHOP,
            item_identity=ALLIANCE_FALLBACK_ITEM,
            currency_identity=ALLIANCE_CURRENCY,
            unit_price=1000, balance=79999, stock=10055, item_quantity=11052,
            rarity=1, available=True,
            offer_identity="other:one-star-gear-enhance-material",
        )
        choice = alliance_shop_choice(
            (weekly_offer,), fallback_offer,
            weekly_inventory_complete=True, fallback_inventory_complete=True,
        )
        self.selection_choice = choice
        selected_offer = choice.offer

        def offer_readiness(offer):
            return {
                "shop_identity": offer.shop_identity,
                "item_identity": offer.item_identity,
                "currency_identity": offer.currency_identity,
                "unit_price": offer.unit_price,
                "balance": offer.balance,
                "stock": offer.stock,
                "rarity": offer.rarity,
                "available": offer.available,
                "premium": offer.premium,
                "recognized": offer.recognized,
                "offer_identity": offer.offer_identity,
            }

        selection_evidence = {
            "weekly_inventory": {
                "complete": True, "reason": "",
                "frame_refs": ("alliance-weekly-offers.png",),
                "frame_sha256s": (_C_EVIDENCE_SHA256,),
            },
            "weekly_offers": (offer_readiness(weekly_offer),),
            "fallback_inventory": {
                "complete": True, "reason": "",
                "frame_refs": ("alliance-other-offers.png",),
                "frame_sha256s": (_C_EVIDENCE_SHA256,),
            },
            "fallback_offer": offer_readiness(fallback_offer),
        }
        input_count = transport_calls = committed = 0
        error = None
        unknown = False
        try:
            for index in range(ALLIANCE_SHOP_MAX_INPUTS):
                checkpoint()
                self.inputs.append((identity.reset_id, index, "alliance-shop-input"))
                input_count += 1
                if index == self.PURCHASE_INPUT:
                    transport_calls = 1
                    if self.partial:
                        unknown = True
                        error = RuntimeError("Alliance Shop purchase successor is unknown")
                        break
                    committed = 1
                    self.actions += 1
                if self.on_input:
                    self.on_input(index)
        except Exception as exc:
            error = exc

        status = "unresolved" if unknown else "blocked" if error else "complete_for_reset"
        result = _guarded_c_payload(
            flow_id=ALLIANCE_SHOP_FLOW_ID,
            product_id=ALLIANCE_SHOP_PRODUCT_ID,
            product_revision=ALLIANCE_SHOP_PRODUCT_REVISION,
            profile_id=ALLIANCE_SHOP_PROFILE_ID,
            identity=identity, previous_reset=previous_reset,
            occurrence_key=occurrence_key, stop=self.stop, started_at=started,
            input_count=input_count, max_inputs=ALLIANCE_SHOP_MAX_INPUTS,
            max_actions=1, status=status, error=error, effect_unknown=unknown,
        )
        result.update(
            purchase_transport_calls=transport_calls,
            committed_action_count=committed,
            prior_confirmed_action_count=0,
            offer_effect_verified=committed == 1 and error is None,
            selected_offer=({
                "shop_identity": selected_offer.shop_identity,
                "offer_identity": selected_offer.offer_identity,
                "item_identity": selected_offer.item_identity,
                "currency_identity": selected_offer.currency_identity,
                "rarity": selected_offer.rarity,
                "unit_price": selected_offer.unit_price,
                "balance_before": selected_offer.balance,
                "stock_before": selected_offer.stock,
                "item_quantity_before": selected_offer.item_quantity,
                "quantity": choice.quantity,
                "total": selected_offer.unit_price * choice.quantity,
            } if transport_calls else None),
            selection_evidence=selection_evidence,
            source_frame={
                "frame_path": "alliance-shop-home.png",
                "frame_sha256": _C_EVIDENCE_SHA256,
            },
        )
        self.last_result = result
        if error is not None:
            raise GuardedRoutePartialResultError(str(error), result) from error
        return result


class GuardedDailyShopsRunner:
    """Mapping-shaped per-tab fake preserving confirmed purchases across service pulses."""

    ACTION_INPUTS = {"ruins": 12, "rare_earth": 24}

    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs, self.occurrence_keys = [], [], []
        self.confirmed_tabs = set()
        self.reset_id = None
        self.actions = 0
        self.partial = False
        self.rare_earth_unaffordable = False
        self.on_input = self.on_entry = None
        self.last_result = None
        self.last_identity = None

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
        if identity.reset_id != self.reset_id:
            self.reset_id = identity.reset_id
            self.confirmed_tabs = set()
        self.last_identity = identity
        if self.on_entry:
            self.on_entry()

        started = self.stop.now
        input_count = transport_calls = committed = 0
        error = None
        unknown = False
        rows = {}
        try:
            for index in range(DAILY_SHOPS_MAX_INPUTS):
                checkpoint()
                self.inputs.append((identity.reset_id, index, "daily-shops-input"))
                input_count += 1
                tab = "ruins" if index == self.ACTION_INPUTS["ruins"] else (
                    "rare_earth" if index == self.ACTION_INPUTS["rare_earth"] else None
                )
                if tab is not None:
                    if tab in self.confirmed_tabs:
                        rows[tab] = self._tab_result(
                            identity, tab, status="already_confirmed",
                        )
                    elif tab == "rare_earth" and self.rare_earth_unaffordable:
                        rows[tab] = self._tab_result(identity, tab, status="deferred")
                    else:
                        transport_calls += 1
                        if self.partial and tab == "rare_earth":
                            unknown = True
                            rows[tab] = self._tab_result(
                                identity, tab, status="unresolved",
                            )
                            error = RuntimeError("Daily Shops second-tab successor is unknown")
                            break
                        committed += 1
                        self.actions += 1
                        self.confirmed_tabs.add(tab)
                        rows[tab] = self._tab_result(identity, tab, status="confirmed")
                if self.on_input:
                    self.on_input(index)
        except Exception as exc:
            error = exc

        # Both tabs always have a canonical per-reset result, including on early interruption.
        for tab in ("ruins", "rare_earth"):
            rows.setdefault(tab, self._tab_result(
                identity, tab,
                status="already_confirmed" if tab in self.confirmed_tabs else "blocked",
            ))
        status = (
            "unresolved" if unknown
            else "blocked" if error
            else "deferred" if any(row["status"] == "deferred" for row in rows.values())
            else "complete_for_reset"
        )
        result = _guarded_c_payload(
            flow_id=DAILY_SHOPS_FLOW_ID,
            product_id=DAILY_SHOPS_PRODUCT_ID,
            product_revision=DAILY_SHOPS_PRODUCT_REVISION,
            profile_id=DAILY_SHOPS_PROFILE_ID,
            identity=identity, previous_reset=previous_reset,
            occurrence_key=occurrence_key, stop=self.stop, started_at=started,
            input_count=input_count, max_inputs=DAILY_SHOPS_MAX_INPUTS,
            max_actions=2, status=status, error=error, effect_unknown=unknown,
        )
        result.update(
            purchase_transport_calls=transport_calls,
            committed_action_count=committed,
            tab_results=rows,
            source_frame={
                "frame_path": "daily-shops-home.png",
                "frame_sha256": _C_EVIDENCE_SHA256,
            },
        )
        self.last_result = result
        if error is not None:
            raise GuardedRoutePartialResultError(str(error), result) from error
        return result

    @staticmethod
    def _tab_result(identity, tab, *, status):
        if tab == "ruins":
            shop, item, currency = RUINS_SHOP, RUINS_CHIP_ITEM, RUINS_CURRENCY
            component, price, balance, stock, item_count = (
                "ruins_shop", 15, 16649, 100, 4,
            )
            quantity = 100
        else:
            shop, item, currency = RARE_EARTH_SHOP, RARE_EARTH_MODULE_ITEM, RARE_EARTH_CURRENCY
            component, price, balance, stock, item_count = (
                "rare_earth_shop", 13800, 211995, 20, 4,
            )
            quantity = 15
        key_identity = SchedulerIdentity(
            identity.account_id, identity.server_id, identity.reset_id,
            DAILY_SHOPS_PRODUCT_ID,
        )
        confirmed = status in {"confirmed", "already_confirmed"}
        deferred = status == "deferred"
        if deferred:
            balance, quantity, total = 0, 0, None
        else:
            total = quantity * price if confirmed else None
        row = {
            "status": status,
            "effect_verified": confirmed,
            "action_key": canonical_purchase_action_key(
                DAILY_SHOPS_FLOW_ID, DAILY_SHOPS_PRODUCT_ID, key_identity, component,
            ),
            "shop_identity": shop,
            "item_identity": item,
            "currency_identity": currency,
            "rarity": 3,
            "offer_identity": f"{component}:current-offer",
            "unit_price": price,
            "balance_before": balance,
            "stock_before": stock,
            "item_quantity_before": item_count,
            "quantity": quantity,
            "total": total,
            "source_frame_ref": f"{component}-offer.png",
            "source_frame_sha256": _C_EVIDENCE_SHA256,
        }
        if deferred:
            row["reason"] = "TAB_INSUFFICIENT_CURRENCY"
        return row


_D_PRODUCTION_SHA256 = "b" * 64
_D_HOME_SHA256 = "c" * 64
_D_BEFORE_SHA256 = "d" * 64
_D_AFTER_SHA256 = "e" * 64


def _guarded_d_frame(path, sha256, now, ordinal=1):
    return {
        "frame_path": path,
        "frame_sha256": sha256,
        "observed_utc": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z"),
        "capture_ordinal": ordinal,
    }


def _guarded_d_action_evidence(action, now, ordinal, *, after_sha256):
    return {
        "before": _guarded_d_frame(
            f"{action}-before.png", hashlib.sha256(f"{action}:before".encode()).hexdigest(),
            now, ordinal,
        ),
        "after": _guarded_d_frame(
            f"{action}-after.png", after_sha256, now, ordinal + 1,
        ),
    }


def _guarded_d_backend(completed):
    backend = derive_resource_runtime_identity(
        resource_fixed_runtime_binding(),
        datetime.fromtimestamp(completed, timezone.utc),
    )
    return {
        "runtime_scope": backend.runtime_scope,
        "account_id": backend.account_id,
        "server_id": backend.server_id,
        "backend_reset_id": backend.reset_id,
        "assurance": backend.assurance.value,
        "runtime_binding_digest": backend.runtime_binding_digest,
        "reset_start_utc": backend.reset_start_utc,
        "reset_deadline_utc": backend.reset_deadline_utc,
        "evidence_refs": list(backend.evidence_refs),
    }


def _guarded_d_envelope(
    *, flow_id, product_id, product_revision, profile_id, identity,
    occurrence_key, completed_at, input_count, status, reason, error, unknown,
):
    result = {
        "flow_id": flow_id,
        "product_id": product_id,
        "product_revision": product_revision,
        "task_id": product_id,
        "account_id": identity.account_id,
        "server_id": identity.server_id,
        "reset_id": identity.reset_id,
        "backend_identity": _guarded_d_backend(completed_at),
        "native_occurrence_key": occurrence_key,
        "occurrence_key": occurrence_key,
        "completed_at_utc": completed_at,
        "runtime_profile_id": profile_id,
        "time_basis": "utc",
        "input_count": input_count,
        "total_input_count": input_count,
        "session_input_count": input_count,
        "runtime_input_count": input_count,
        "status": status,
        "reason": reason,
        "accounting_verified": True,
        "terminal_home_verified": not error,
        "effect_reconciliation_required": unknown,
        "identical_retry_denied": unknown,
    }
    if not error:
        result.update(
            terminal_home_state="HOME_BASE",
            terminal_home_recognized=True,
            terminal_home_frame=_guarded_d_frame(
                "guarded-d-home.png", _D_HOME_SHA256, completed_at,
            ),
            terminal_home_frame_path="guarded-d-home.png",
            terminal_home_frame_sha256=_D_HOME_SHA256,
        )
    return result


class GuardedNanoMaterialProductionRunner:
    """Mapping-shaped zero-cost maintenance fake with restart-safe timer state."""

    CLAIM_INPUT = 5
    START_INPUT = 10

    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs, self.occurrence_keys = [], [], []
        self.transition_order = []
        self.production_state = "idle"
        self.production_due_at = None
        self.partial = False
        self.partial_action = None
        self.on_input = self.on_entry = None
        self.last_result = None
        self.last_identity = None
        self.effects = 0

    def __call__(self, identity, previous_reset_id, checkpoint, *,
                 runtime_input_lock, occurrence_key):
        checkpoint()
        runtime_input_lock.assert_held(
            runtime_input_lock.owner, runtime_input_lock.invocation_id,
        )
        self.calls.append((identity, previous_reset_id))
        self.occurrence_keys.append(occurrence_key)
        self.last_identity = identity
        if self.on_entry:
            self.on_entry()

        if (self.production_state == "active" and self.production_due_at is not None
                and self.stop.now >= self.production_due_at):
            self.production_state = "complete"
        input_count = transport_calls = committed = 0
        error = None
        unknown = False
        last_action_evidence = None
        production_action_evidence = {}
        try:
            for index in range(NANO_MATERIAL_PRODUCTION_MAX_INPUTS):
                checkpoint()
                self.inputs.append((identity.reset_id, index, "nano-material-production-input"))
                input_count += 1
                action = (
                    "claim" if index == self.CLAIM_INPUT and self.production_state == "complete"
                    else "start" if index == self.START_INPUT and self.production_state == "idle"
                    else None
                )
                if action is not None:
                    self.transition_order.append(action)
                    transport_calls += 1
                    should_fail = self.partial and (
                        self.partial_action is None or self.partial_action == action
                    )
                    if should_fail:
                        unknown = True
                        error = RuntimeError(f"Nano Material Production {action} successor is unknown")
                        last_action_evidence = {
                            "before": _guarded_d_frame(
                                "nano-material-production-before.png", _D_BEFORE_SHA256,
                                self.stop.now,
                            ),
                            "after": _guarded_d_frame(
                                "nano-material-production-after.png", _D_AFTER_SHA256,
                                self.stop.now, 2,
                            ),
                        }
                        production_action_evidence[action] = last_action_evidence
                        break
                    committed += 1
                    self.effects += 1
                    last_action_evidence = _guarded_d_action_evidence(
                        f"nano-material-production-{action}", self.stop.now,
                        transport_calls * 2 - 1,
                        after_sha256=(
                            _D_AFTER_SHA256 if action == "claim" else _D_PRODUCTION_SHA256
                        ),
                    )
                    production_action_evidence[action] = last_action_evidence
                    if action == "claim":
                        self.production_state = "idle"
                        self.production_due_at = None
                    else:
                        self.production_state = "active"
                        self.production_due_at = self.stop.now + NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
                if self.on_input:
                    self.on_input(index)
        except Exception as exc:
            error = exc

        completed = self.stop.now
        status = (
            "unresolved" if unknown else "blocked" if error
            else "completed" if transport_calls else "deferred"
        )
        frame = _guarded_d_frame(
            "nano-material-production-state.png", _D_PRODUCTION_SHA256, completed, 2,
        )
        if committed == transport_calls and last_action_evidence is not None:
            frame = last_action_evidence["after"]
        timer = (
            max(1, min(NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
                       int(self.production_due_at - completed)))
            if not error and self.production_state == "active"
            and self.production_due_at is not None else None
        )
        result = _guarded_d_envelope(
            flow_id=NANO_MATERIAL_PRODUCTION_FLOW_ID,
            product_id=NANO_MATERIAL_PRODUCTION_PRODUCT_ID,
            product_revision=NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION,
            profile_id=NANO_MATERIAL_PRODUCTION_PROFILE_ID,
            identity=identity, occurrence_key=occurrence_key,
            completed_at=completed, input_count=input_count,
            status=status,
            reason=(
                str(error) if error else
                "MATERIAL_PRODUCTION_ACTIVE_DUE_REFRESH_ONLY" if not transport_calls else
                "MATERIAL_PRODUCTION_CLAIMED_THEN_RESTARTED" if transport_calls == 2 else
                "MATERIAL_PRODUCTION_IDLE_STARTED"
            ),
            error=error is not None, unknown=unknown,
        )
        result.update(
            production_transport_calls=transport_calls,
            attempted_action_count=transport_calls,
            attempted_action_count_known=True,
            action_evidence_required=False,
            committed_action_count=committed,
            zero_resource_cost_confirmed=bool(committed),
            production_state=self.production_state if not unknown else None,
            active_production_count=int(self.production_state == "active") if not unknown else None,
            completed_batch_count=int(self.production_state == "complete") if not unknown else None,
            production_duration_seconds=NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
            timer_seconds_remaining=timer,
            production_occurrence_key=occurrence_key,
            production_target_identity=NANO_MATERIAL_PRODUCTION_TARGET,
            production_state_frame=frame,
            production_state_observation_sha256=frame["frame_sha256"],
            production_evidence_refs=("nano-material-production-state.png",),
            production_action_evidence=production_action_evidence,
        )
        if not error:
            result["next_eligible_at"] = completed + timer
        if last_action_evidence is not None:
            result["last_action_evidence"] = last_action_evidence
        self.last_result = result
        if error is not None:
            raise GuardedRoutePartialResultError(str(error), result) from error
        return result


class GuardedNanoweaponRunner:
    """Mapping-shaped same-visit fake for production-first Normal Craft pulses."""

    PRODUCTION_CLAIM_INPUT = 4
    PRODUCTION_START_INPUT = 6
    CRAFT_CLAIM_INPUT = 10
    CRAFT_START_INPUT = 12

    def __init__(self, stop, output):
        self.stop, self.output = stop, output
        self.calls, self.inputs, self.occurrence_keys = [], [], []
        self.phase_order, self.action_order = [], []
        self.production_state = "idle"
        self.production_due_at = None
        self.craft_state = "idle"
        self.craft_due_at = None
        self.craft_start_reset_id = None
        self.starts_this_reset = 0
        self.reset_id = None
        self.nano_parts_balance = 200
        self.materials_affordable = None
        self.partial = False
        self.fail_action = "craft_start"
        self.on_input = self.on_entry = None
        self.last_result = None
        self.last_identity = None
        self.effects = 0

    def __call__(self, identity, previous_reset_id, checkpoint, *,
                 runtime_input_lock, occurrence_key):
        checkpoint()
        runtime_input_lock.assert_held(
            runtime_input_lock.owner, runtime_input_lock.invocation_id,
        )
        self.calls.append((identity, previous_reset_id))
        self.occurrence_keys.append(occurrence_key)
        self.last_identity = identity
        if identity.reset_id != self.reset_id:
            self.starts_this_reset = 0
            self.reset_id = identity.reset_id
        if self.on_entry:
            self.on_entry()

        if (self.production_state == "active" and self.production_due_at is not None
                and self.stop.now >= self.production_due_at):
            self.production_state = "complete"
        if self.production_state == "active" and self.production_due_at is None:
            self.production_due_at = self.stop.now + NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
        if (self.craft_state == "active" and self.craft_due_at is not None
                and self.stop.now >= self.craft_due_at):
            self.craft_state = "complete"

        input_count = production_calls = craft_calls = claim_calls = start_calls = 0
        committed = 0
        error = None
        unknown = False
        last_action_evidence = None
        production_action_evidence = {}
        craft_action_evidence = {}
        precraft_balance = self.nano_parts_balance
        phase = "production"
        production_frame = _guarded_d_frame(
            "nanoweapon-production-state.png", _D_PRODUCTION_SHA256, self.stop.now,
        )

        def dispatch(action: str, *, production: bool) -> bool:
            nonlocal production_calls, craft_calls, claim_calls, start_calls
            nonlocal committed, error, unknown, last_action_evidence
            self.action_order.append(f"{'production' if production else 'craft'}:{action}")
            if production:
                production_calls += 1
            else:
                craft_calls += 1
                if action == "claim":
                    claim_calls += 1
                else:
                    start_calls += 1
            failure_action = f"{'production' if production else 'craft'}_{action}"
            if self.partial and failure_action == self.fail_action and not unknown:
                unknown = True
                error = RuntimeError(f"Nanoweapon {failure_action} successor is unknown")
                last_action_evidence = {
                    "before": _guarded_d_frame(
                        "nanoweapon-action-before.png", _D_BEFORE_SHA256,
                        self.stop.now,
                    ),
                    "after": _guarded_d_frame(
                        "nanoweapon-action-after.png", _D_AFTER_SHA256,
                        self.stop.now, 2,
                    ),
                }
                if production:
                    production_action_evidence[action] = last_action_evidence
                return False
            committed += 1
            self.effects += 1
            evidence = _guarded_d_action_evidence(
                f"nanoweapon-{'production' if production else 'craft'}-{action}",
                self.stop.now, committed * 2 - 1,
                after_sha256=(
                    _D_PRODUCTION_SHA256 if production and action == "start"
                    else hashlib.sha256(
                        f"nanoweapon:{production}:{action}:after".encode(),
                    ).hexdigest()
                ),
            )
            last_action_evidence = evidence
            if production:
                production_action_evidence[action] = evidence
            else:
                craft_action_evidence[action] = evidence
            if production:
                if action == "claim":
                    self.production_state = "idle"
                    self.production_due_at = None
                else:
                    self.production_state = "active"
                    self.production_due_at = self.stop.now + NANO_MATERIAL_PRODUCTION_DURATION_SECONDS
            elif action == "claim":
                self.craft_state = "idle"
                self.craft_due_at = None
            else:
                if self.nano_parts_balance is not None:
                    self.nano_parts_balance -= NANO_PARTS_REQUIRED
                self.craft_state = "active"
                self.craft_due_at = self.stop.now + NORMAL_CRAFT_DURATION_SECONDS
                self.craft_start_reset_id = identity.reset_id
                self.starts_this_reset += 1
            return True

        try:
            for index in range(NANOWEAPON_MAX_INPUTS):
                checkpoint()
                self.inputs.append((identity.reset_id, index, "nanoweapon-input"))
                input_count += 1

                if phase == "production":
                    if index == 0:
                        self.phase_order.append("production-maintenance")
                    production_action = (
                        "claim" if index == self.PRODUCTION_CLAIM_INPUT
                        and self.production_state == "complete"
                        else "start" if index == self.PRODUCTION_START_INPUT
                        and self.production_state == "idle"
                        else None
                    )
                    if production_action and not dispatch(production_action, production=True):
                        break
                    if index == self.PRODUCTION_START_INPUT:
                        phase = "craft"
                if phase == "craft":
                    if index == self.CRAFT_CLAIM_INPUT:
                        self.phase_order.append("normal-craft")
                    craft_action = (
                        "claim" if index == self.CRAFT_CLAIM_INPUT
                        and self.craft_state == "complete"
                        else "start" if index == self.CRAFT_START_INPUT
                        and self.craft_state == "idle"
                        and self.starts_this_reset == 0
                        and (
                            self.materials_affordable if self.materials_affordable is not None
                            else self.nano_parts_balance is not None
                            and self.nano_parts_balance >= NANO_PARTS_REQUIRED
                        )
                        else None
                    )
                    if craft_action and not dispatch(craft_action, production=False):
                        break
                if self.on_input:
                    self.on_input(index)
        except Exception as exc:
            error = exc

        completed = self.stop.now
        successful = error is None
        status = (
            "unresolved" if unknown else "blocked" if error
            else "completed" if start_calls else "deferred"
        )
        production_known = self.production_state == "active"
        production_timer = (
            max(1, min(NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
                       int(self.production_due_at - completed)))
            if production_known and self.production_due_at is not None else None
        )
        if "start" in production_action_evidence and production_known:
            production_frame = production_action_evidence["start"]["after"]
        craft_timer = (
            max(1, min(NORMAL_CRAFT_DURATION_SECONDS, int(self.craft_due_at - completed)))
            if successful and self.craft_state == "active" and self.craft_due_at is not None
            else 0
        )
        game_day_id = identity.reset_id
        prior_start_known = (
            self.craft_start_reset_id is not None
            and self.craft_start_reset_id != identity.reset_id
        )
        due_reason = (
            "current_reset_start" if self.starts_this_reset > 0
            else "previous_reset_active_timer" if self.craft_state == "active" and prior_start_known
            else "observed_active_timer" if self.craft_state == "active"
            else "known_material_shortage"
        )
        if self.craft_state == "complete":
            due_reason = "current_reset_start" if self.starts_this_reset > 0 else "known_material_shortage"
        result = _guarded_d_envelope(
            flow_id=NANOWEAPON_FLOW_ID,
            product_id=NANOWEAPON_PRODUCT_ID,
            product_revision=NANOWEAPON_PRODUCT_REVISION,
            profile_id=NANOWEAPON_PROFILE_ID,
            identity=identity, occurrence_key=occurrence_key,
            completed_at=completed, input_count=input_count,
            status=status,
            reason=str(error) if error else "NANOWEAPON_SAME_VISIT_ROUTE_COMPLETE",
            error=error is not None, unknown=unknown,
        )
        result.update(
            production_transport_calls=production_calls,
            craft_transport_calls=craft_calls,
            craft_claim_transport_calls=claim_calls,
            craft_start_transport_calls=start_calls,
            nanoweapon_dispatch_count=production_calls + craft_calls,
            attempted_action_count=production_calls + craft_calls,
            attempted_action_count_known=True,
            committed_action_count=committed,
            prior_material_production_reconciled=production_known,
            zero_resource_cost_confirmed=production_known,
            production_state="active" if production_known else None,
            production_active_count=1 if production_known else None,
            production_duration_seconds=NANO_MATERIAL_PRODUCTION_DURATION_SECONDS,
            production_timer_seconds_remaining=production_timer,
            production_next_eligible_at=(
                completed + production_timer if production_timer is not None else None
            ),
            production_occurrence_key=occurrence_key,
            production_target_identity=NANO_MATERIAL_PRODUCTION_TARGET,
            production_state_frame=production_frame,
            production_state_observation_sha256=_D_PRODUCTION_SHA256,
            production_action_evidence=production_action_evidence,
            game_day_id=game_day_id,
            craft_state=self.craft_state if successful else None,
            craft_active_count=1 if successful and self.craft_state == "active" else 0,
            active_craft_timer_seconds_remaining=craft_timer if successful else None,
            craft_duration_seconds=NORMAL_CRAFT_DURATION_SECONDS,
            craft_start_confirmed=bool(self.craft_start_reset_id is not None),
            craft_start_reset_id=self.craft_start_reset_id,
            starts_this_reset=self.starts_this_reset,
            due_reason=due_reason if successful else None,
            precraft_nano_parts_balance=precraft_balance if start_calls and successful else None,
            nano_parts_balance=self.nano_parts_balance,
            observation_interval_seconds=300,
        )
        if "claim" in craft_action_evidence:
            result.update(
                craft_claim_confirmed=True,
                craft_claim_occurrence_key=occurrence_key,
                craft_claim_action_evidence=craft_action_evidence["claim"],
                craft_claim_action_key=(
                    f"{NANOWEAPON_PRODUCT_ID}:claim:{identity.reset_id}:"
                    + hashlib.sha256(
                        "\0".join((
                            FIXED_RUNTIME_SCOPE, identity.account_id, identity.server_id,
                            occurrence_key,
                        )).encode("utf-8"),
                    ).hexdigest()
                ),
            )
        if "start" in craft_action_evidence:
            result["craft_start_action_evidence"] = craft_action_evidence["start"]
            result["craft_start_action_key"] = (
                f"{NANOWEAPON_PRODUCT_ID}:start:{identity.reset_id}:"
                + hashlib.sha256(
                    "\0".join((
                        FIXED_RUNTIME_SCOPE, identity.account_id, identity.server_id, "",
                    )).encode("utf-8"),
                ).hexdigest()
            )
        if successful:
            if due_reason in {"previous_reset_active_timer", "observed_active_timer"}:
                craft_due = completed + craft_timer
            elif due_reason == "known_material_shortage":
                craft_due = completed + 300
            else:
                craft_due = (int(completed) // 86400 + 1) * 86400
                if self.craft_state == "active":
                    craft_due = min(craft_due, completed + craft_timer)
            result["next_eligible_at"] = min(
                result["production_next_eligible_at"], craft_due,
            )
        if last_action_evidence is not None:
            result["last_action_evidence"] = last_action_evidence
        self.last_result = result
        if error is not None:
            raise GuardedRoutePartialResultError(str(error), result) from error
        return result


_E_HOME_FRAME = {
    "frame_path": "synthetic-e-home.png",
    "frame_sha256": hashlib.sha256(b"synthetic-e-home").hexdigest(),
}


def _hero_duel_cycle_proof(identity, event_identity: str, ordinal: int, opponent: str) -> dict:
    reset_id = identity.reset_id
    key = {
        "runtime_scope": FIXED_RUNTIME_SCOPE,
        "account_id": identity.account_id,
        "server_id": identity.server_id,
        "game_day_id": reset_id,
        "ordinal": ordinal,
    }
    free_before = 4 - ordinal
    return {
        "ordinal": ordinal,
        "reset_id": reset_id,
        "event_identity": event_identity,
        "listed_opponent_display": opponent,
        "entry_action_key": hero_duel_action_key(
            **key, action_kind="hero_duel_free_entry",
        ),
        "flee_action_key": hero_duel_action_key(
            **key, action_kind="hero_duel_flee",
        ),
        "free_before": free_before,
        "free_after": free_before - 1,
        "wave_text": "Wave 1/1",
        "battle_board_verified": True,
        "exit_confirmed": True,
        "flee_confirmed": True,
        "loss_result_seen": True,
        "tap_to_continue_confirmed": True,
        "result_frame_sha256": hashlib.sha256(
            f"hero-duel-result-{ordinal}".encode(),
        ).hexdigest(),
    }


def _hero_duel_native_result(
    identity, input_count: int, *, observed_at: float,
    attempted: bool = False, interrupted: bool = False,
) -> dict:
    event_identity = f"survival_{identity.reset_id}_ends_28333333"
    committed_ordinals = [] if attempted or interrupted else [1, 2, 3]
    selected_opponents = [
        f"Free opponent {ordinal}" for ordinal in range(1, (1 if attempted else 3) + 1)
    ] if not interrupted else []
    proofs = [
        _hero_duel_cycle_proof(
            identity, event_identity, ordinal, selected_opponents[ordinal - 1],
        )
        for ordinal in committed_ordinals
    ]
    dispatches = 1 if attempted else 0 if interrupted else 3
    return {
        "flow_id": HERO_DUEL_FLOW_ID,
        "product_id": HERO_DUEL_PRODUCT_ID,
        "product_revision": HERO_DUEL_PRODUCT_REVISION,
        "status": (
            "reconciliation_required" if attempted
            else "blocked" if interrupted else "complete_for_reset"
        ),
        "reason": (
            "hero_duel_entry_successor_unknown" if attempted
            else "hero_duel_pre_entry_interrupted" if interrupted
            else "three_free_loss_cycles_home_verified"
        ),
        "runtime_profile_id": HERO_DUEL_PROFILE_ID,
        "reset_id": identity.reset_id,
        "hero_duel_event_identity": event_identity if not interrupted else None,
        "current_event_active": not interrupted,
        "initial_free_entries_remaining": 3 if not interrupted else None,
        "ui_inferred_prior_uses": 0 if not interrupted else None,
        "expected_defense_hero_ids": [] if interrupted else [
            "ulrik", "mccarty", "meyers", "marlowe", "ephraim",
        ],
        "defense_save_confirmed": not interrupted,
        "selected_listed_opponents": selected_opponents,
        "duel_dispatch_count": dispatches,
        "entry_transport_calls": dispatches,
        "flee_transport_calls": 0 if attempted or interrupted else 3,
        "defense_save_transport_calls": int(not interrupted),
        "defense_selection_transport_calls": 0 if interrupted else 5,
        "flee_confirmed_count": 0 if attempted or interrupted else 3,
        "committed_action_count": len(proofs),
        "canonical_confirmed_cycle_ordinals": committed_ordinals,
        "cycle_proofs": proofs,
        "final_free_entries_remaining": 0 if not attempted and not interrupted else None,
        "availability_observed_at_utc": observed_at if not attempted and not interrupted else None,
        "total_input_count": input_count,
        "input_accounting_verified": True,
        "terminal_home_verified": not attempted and not interrupted,
        "terminal_home_frame": (
            dict(_E_HOME_FRAME) if not attempted and not interrupted else None
        ),
        "effect_reconciliation_required": attempted,
        "identical_retry_denied": attempted,
        "accounting_verified": True,
        "no_work": False,
    }


def _research_selection_evidence() -> dict:
    return {
        "recommendation_position": 1,
        "queue2_activate_tapped": False,
        "prerequisites_known": True,
        "prerequisites_met": True,
        "prerequisite_evidence": ["research-center-lv-24"],
        "requirements_scrolled": True,
        "research_start_visible": True,
        "control_class": "RESEARCH_START",
        "research_now_target_identity": "research-now-diamonds",
        "research_now_tapped": False,
        "overlay_state": "none_observed",
    }


def _research_native_result(
    stop: VirtualStop, identity, input_count: int, *, mode: str = "completed",
) -> dict:
    completed_at = stop.now
    base = {
        "flow_id": RECOMMENDED_RESEARCH_FLOW_ID,
        "product_id": RECOMMENDED_RESEARCH_PRODUCT_ID,
        "product_revision": RECOMMENDED_RESEARCH_PRODUCT_REVISION,
        "status": mode,
        "reason": "recommended_research_native_result",
        "terminal_home_verified": True,
        "terminal_home_frame": dict(_E_HOME_FRAME),
        "terminal_home_frame_sha256": _E_HOME_FRAME["frame_sha256"],
        "research_transport_calls": 0,
        "committed_action_count": 0,
        "total_action_count": 0,
        "total_input_count": input_count,
        "input_count": input_count,
        "session_input_count": input_count,
        "runtime_input_count": input_count,
        "accounting_verified": True,
        "effect_reconciliation_required": False,
        "identical_retry_denied": mode == "already_complete",
        "time_basis": "utc",
        "completed_at_utc": completed_at,
        "next_due_utc": None,
        "game_day_id": identity.reset_id,
    }
    if mode == "unresolved":
        return {
            **base,
            "status": "unresolved",
            "reason": "research_start_dispatched_successor_unknown",
            "research_transport_calls": 1,
            "total_action_count": 1,
            "terminal_home_verified": False,
            "terminal_home_frame": None,
            "terminal_home_frame_sha256": None,
            "effect_reconciliation_required": True,
            "identical_retry_denied": True,
        }
    if mode == "deferred_busy":
        return {
            **base,
            "status": "deferred",
            "queue1_state": "busy",
            "queue1_remaining_seconds": 731,
            "next_due_utc": completed_at + 731,
            "identical_retry_denied": False,
        }
    if mode == "deferred_shortage":
        costs = {"food": 100, "wood": 20, "steel": 0, "gas": 0}
        balances = {"food": 20, "wood": 80, "steel": 10, "gas": 10}
        return {
            **base,
            **_research_selection_evidence(),
            "status": "deferred",
            "queue1_state": "idle",
            "queue1_remaining_seconds": None,
            "observation_interval_seconds": 300,
            "next_due_utc": completed_at + 300,
            "first_recommendation_identity": "troop-load-ii",
            "target_identity": "recommended-research:troop-load-ii:detail-research-button",
            "exact_resource_costs": costs,
            "exact_resource_balances": balances,
            "shortages": [{"resource": "food", "shortage": 80}],
            "identical_retry_denied": False,
        }
    if mode == "blocked":
        return {
            **base,
            "status": "blocked",
            "terminal_home_verified": False,
            "terminal_home_frame": None,
            "terminal_home_frame_sha256": None,
        }
    if mode == "already_complete":
        return {**base, "status": mode, "already_confirmed": True}

    costs = {"food": 100, "wood": 20, "steel": 15, "gas": 5}
    prebalances = {"food": 3_003_682, "wood": 757_050, "steel": 129_702, "gas": 47_775}
    target = "recommended-research:troop-load-ii:detail-research-button"
    return {
        **base,
        **_research_selection_evidence(),
        "status": "completed",
        "completed": True,
        "start_semantically_verified": True,
        "queue1_state": "idle",
        "queue1_remaining_seconds": None,
        "research_transport_calls": 1,
        "committed_action_count": 1,
        "total_action_count": 1,
        "first_recommendation_identity": "troop-load-ii",
        "active_technology": "troop-load-ii",
        "target_identity": target,
        "remaining_seconds": 3_600,
        "research_duration_seconds": 21_413,
        "next_due_utc": completed_at + 3_600,
        "exact_resource_costs": costs,
        "exact_resource_prebalances": prebalances,
        "start_action": {
            "target_identity": target,
            "source_frame": "frames/research-start-source.png",
            "successor_frame": "frames/research-active-successor.png",
        },
        "identical_retry_denied": True,
    }


def _food_farm_native_result(
    identity, occurrence_key: str, input_count: int, *, mode: str = "completed",
    collection_attempted: bool = True, collection_confirmed: bool = True,
    boost_attempted: bool = True, boost_confirmed: bool = True,
    collection_collected: bool | None = None,
) -> dict:
    farm_identity = "home.building.farm.02"
    food_before = None if mode == "settled_home" else "1000"
    food_after = None if mode == "settled_home" else "1000" if mode == "settled_radial" else "1300"
    collected = collection_confirmed and mode not in {"settled_radial", "settled_home"}
    if collection_collected is not None:
        collected = collection_collected
    successor = "home" if mode == "settled_home" else "radial" if mode == "settled_radial" else "hud_tick"
    action_key = {
        "runtime_scope": FIXED_RUNTIME_SCOPE,
        "account_id": identity.account_id,
        "server_id": identity.server_id,
        "reset_id": identity.reset_id,
    }
    collection_key = food_farm_boost_daily_action_key(
        **action_key, phase="collection", collection_occurrence_id="1",
    )
    boost_key = food_farm_boost_daily_action_key(**action_key, phase="boost")
    base = {
        "status": mode,
        "reason": "FOOD_FARM_NATIVE_RESULT",
        "farm_identity": farm_identity,
        "reset_id": identity.reset_id,
        "collection_transport_calls": int(collection_attempted),
        "collection_count": int(collected),
        "collection_effect_accounted": collection_confirmed,
        "collection_occurrence_key": occurrence_key,
        "boost_occurrence_key": boost_key,
        "collection_action_key": collection_key,
        "boost_action_key": boost_key,
        "collection_food_before": food_before if collection_attempted else None,
        "collection_food_after": food_after if collection_attempted and collection_confirmed else None,
        "collection_successor": successor if collection_confirmed else None,
        "boost_transport_calls": int(boost_attempted),
        "food_farm_dispatch_count": int(collection_attempted) + int(boost_attempted),
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "terminal_home_verified": True,
        "terminal_home_frame_sha256": _E_HOME_FRAME["frame_sha256"],
        "terminal_home_frame": _E_HOME_FRAME["frame_path"],
        "total_input_count": input_count,
        "input_count": input_count,
        "session_input_count": input_count,
        "runtime_input_count": input_count,
        "accounting_verified": True,
    }
    if collection_attempted:
        base["collection_action"] = {
            "status": "confirmed" if collection_confirmed else "unresolved",
            "reason": "FOOD_FARM_FIRST_TAP_SETTLED" if collection_confirmed
            else "FOOD_FARM_COLLECTION_REQUIRES_RECONCILIATION",
            "action_key": collection_key,
            "journal_status": "CONFIRMED" if collection_confirmed else "UNRESOLVED",
            "transport_calls": 1,
            "effect_reconciliation_required": not collection_confirmed,
            "successor_frame": "frames/e-farm-collection-successor.png" if collection_confirmed else None,
            "successor_sha256": "a" * 64 if collection_confirmed else None,
        }
    if boost_attempted:
        base["boost_action"] = {
            "status": "confirmed" if boost_confirmed else "unresolved",
            "reason": "FOOD_FARM_BOOST_CONFIRMED_WITH_POSITIVE_TIMER" if boost_confirmed
            else "FOOD_FARM_BOOST_REQUIRES_RECONCILIATION",
            "action_key": boost_key,
            "journal_status": "CONFIRMED" if boost_confirmed else "UNRESOLVED",
            "transport_calls": 1,
            "effect_reconciliation_required": not boost_confirmed,
            "successor_frame": "frames/e-farm-boost-successor.png" if boost_confirmed else None,
            "successor_sha256": "b" * 64 if boost_confirmed else None,
        }
    if mode == "unresolved":
        return {
            **base,
            "status": "unresolved",
            "reason": "FOOD_FARM_COLLECTION_REQUIRES_RECONCILIATION",
            "collection_count": 0,
            "collection_food_after": None,
            "collection_successor": None,
            "collection_effect_accounted": False,
            "boost_transport_calls": 0,
            "food_farm_dispatch_count": 1,
            "effect_reconciliation_required": True,
            "identical_retry_denied": True,
            "terminal_home_verified": False,
            "terminal_home_frame": None,
            "terminal_home_frame_sha256": None,
        }
    if mode == "collection_replay_blocked":
        return {
            **base,
            "status": "blocked",
            "reason": "FOOD_FARM_COLLECTION_REQUIRES_RECONCILIATION",
            "collection_transport_calls": 0,
            "collection_count": 0,
            "collection_effect_accounted": False,
            "boost_transport_calls": 0,
            "food_farm_dispatch_count": 0,
            "effect_reconciliation_required": True,
            "identical_retry_denied": True,
            "terminal_home_verified": False,
            "terminal_home_frame": None,
            "terminal_home_frame_sha256": None,
        }
    if mode == "boost_unresolved":
        return {
            **base,
            "status": "unresolved",
            "reason": "FOOD_FARM_BOOST_REQUIRES_RECONCILIATION",
            "effect_reconciliation_required": True,
            "identical_retry_denied": True,
        }
    if mode == "boost_replay_blocked":
        return {
            **base,
            "status": "blocked",
            "reason": "FOOD_FARM_BOOST_REQUIRES_RECONCILIATION",
            "collection_transport_calls": 0,
            "boost_transport_calls": 0,
            "food_farm_dispatch_count": 0,
            "effect_reconciliation_required": True,
            "identical_retry_denied": True,
            "terminal_home_verified": False,
            "terminal_home_frame": None,
            "terminal_home_frame_sha256": None,
        }
    if mode == "already_active":
        return {
            **base,
            "status": "already_active",
            "collection_transport_calls": 0,
            "collection_count": 0,
            "collection_food_before": None,
            "collection_food_after": None,
            "collection_successor": None,
            "collection_effect_accounted": False,
            "boost_transport_calls": 0,
            "food_farm_dispatch_count": 0,
            "boost_decision": "already_active",
            "active_remaining_seconds": 3_600,
            "active_timer_farm_identity": farm_identity,
        }
    if mode == "diamond_guard":
        return {
            **base,
            "status": "blocked",
            "reason": "FOOD_FARM_DIAMOND_OFFER_UNKNOWN",
            "boost_transport_calls": 0,
            "food_farm_dispatch_count": int(collection_attempted),
            "boost_decision": "diamonds",
        }
    if mode == "blocked":
        return {
            **base,
            "status": "blocked",
            "collection_transport_calls": 0,
            "collection_count": 0,
            "collection_effect_accounted": False,
            "boost_transport_calls": 0,
            "food_farm_dispatch_count": 0,
            "terminal_home_verified": False,
            "terminal_home_frame": None,
            "terminal_home_frame_sha256": None,
        }
    if mode == "already_complete":
        return {
            **base,
            "status": "already_complete",
            "collection_transport_calls": 0,
            "boost_transport_calls": 0,
            "food_farm_dispatch_count": 0,
            "boost_decision": "owned_item",
            "boost_duration_seconds": 86_400,
            "prior_boost_confirmation": {
                "confirmed": True, "frame_sha256": "c" * 64,
            },
            "prior_boost_confirmation_farm_identity": farm_identity,
            "prior_boost_confirmation_duration_seconds": 86_400,
        }
    result = {
        **base,
        "status": "completed",
        "boost_decision": "diamonds" if mode == "diamonds" else "owned_item",
        "boost_cost": 37 if mode == "diamonds" else 1,
        "boost_diamond_balance": 100 if mode == "diamonds" else None,
        "owned_item_unavailable": mode == "diamonds",
        "boost_duration_seconds": 86_400,
        "boost_timer_remaining_seconds": 86_390,
        "boost_timer_farm_identity": farm_identity,
    }
    return result

class _GuardedENativeBoundary:
    """NativeRouteOutcome fake that checkpoints every counted input and keeps DTO attempts exact."""

    def __init__(self, owner, flow_id: str, result_builder, input_budget: int):
        self.owner, self.flow_id = owner, flow_id
        self.result_builder, self.input_budget = result_builder, input_budget
        self.max_inputs = input_budget
        (
            self.product_id, self.product_revision,
            self.runtime_profile_id, self.max_actions,
        ) = {
            HERO_DUEL_FLOW_ID: (
                HERO_DUEL_PRODUCT_ID, HERO_DUEL_PRODUCT_REVISION,
                HERO_DUEL_PROFILE_ID, HERO_DUEL_MAX_ACTIONS,
            ),
            RECOMMENDED_RESEARCH_FLOW_ID: (
                RECOMMENDED_RESEARCH_PRODUCT_ID, RECOMMENDED_RESEARCH_PRODUCT_REVISION,
                RECOMMENDED_RESEARCH_PROFILE_ID, RECOMMENDED_RESEARCH_MAX_ACTIONS,
            ),
            FOOD_FARM_BOOST_FLOW_ID: (
                FOOD_FARM_BOOST_PRODUCT_ID, FOOD_FARM_BOOST_PRODUCT_REVISION,
                FOOD_FARM_BOOST_PROFILE_ID, FOOD_FARM_BOOST_MAX_ACTIONS,
            ),
            HALL_OF_WAR_ADAPTER_FLOW_ID: (
                HALL_OF_WAR_ADAPTER_PRODUCT_ID, HALL_OF_WAR_ADAPTER_PRODUCT_REVISION,
                HALL_OF_WAR_ADAPTER_PROFILE_ID, HALL_OF_WAR_MAX_ACTIONS,
            ),
            TROOP_TRAINING_ADAPTER_FLOW_ID: (
                TROOP_TRAINING_ADAPTER_PRODUCT_ID, TROOP_TRAINING_ADAPTER_PRODUCT_REVISION,
                TROOP_TRAINING_ADAPTER_PROFILE_ID, TROOP_TRAINING_MAX_ACTIONS,
            ),
            WALI_UPGRADE_FLOW_ID: (
                WALI_UPGRADE_PRODUCT_ID, WALI_UPGRADE_PRODUCT_REVISION,
                WALI_UPGRADE_PROFILE_ID, WALI_UPGRADE_MAX_ACTIONS,
            ),
        }[flow_id]
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        self.owner.native_occurrence_keys.append(request.occurrence_key)
        self.owner.current_occurrence_key = request.occurrence_key
        count, failure = 0, None
        try:
            request.runtime_input_lock.assert_held(
                request.runtime_input_lock.owner, request.runtime_input_lock.invocation_id,
            )
            request.validate_identity()
            planned = (
                self.owner.partial_input_count if self.owner.partial
                else self.owner.input_count
            )
            if planned > self.input_budget:
                raise ValueError("fake native input scenario exceeds route budget")
            for index in range(planned):
                request.checkpoint()
                self.owner.inputs.append((request.identity.reset_id, index))
                count += 1
                if self.owner.on_input is not None:
                    self.owner.on_input(index)
        except Exception as exc:
            failure = f"{type(exc).__name__}:{exc}"

        explicit_partial = self.owner.partial and failure is None
        failure = failure or (
            f"{self.flow_id.lower()}_native_successor_unknown" if explicit_partial else None
        )
        result = self.result_builder(
            request.identity, self.owner.stop, count,
            explicit_partial=explicit_partial,
            interrupted=failure is not None and not explicit_partial,
            owner=self.owner,
        )
        successful = failure is None
        outcome = NativeRouteOutcome(
            flow_id=self.flow_id,
            native_result=result if successful else {},
            partial_result=None if successful else result,
            failure=failure,
            invocation_id=f"offline-{self.flow_id.lower()}",
            session_directory=str(request.output_directory),
            startup_recovery=None,
            input_count=count,
            session_input_count=count,
            runtime_input_count=count,
            accounting_verified=True,
        )
        self.owner.last_native_outcome = outcome
        return outcome


class _GuardedEAdapterRunner:
    """Service-facing observer for a real adapter around a fake native DTO boundary."""

    def __init__(self, stop, output_directory, flow_id, input_count, partial_input_count, max_inputs, result_builder, adapter):
        self.stop, self.output_directory = stop, output_directory
        self.flow_id, self.input_count = flow_id, input_count
        self.partial_input_count, self.max_inputs = partial_input_count, max_inputs
        self.partial = False
        self.calls, self.inputs, self.occurrence_keys = [], [], []
        self.native_occurrence_keys = []
        self.last_identity = self.last_result = self.last_native_outcome = None
        self.on_entry = self.on_input = None
        self.attempted_actions = self.confirmed_actions = 0
        boundary = _GuardedENativeBoundary(self, flow_id, result_builder, max_inputs)
        self.adapter = adapter(boundary)

    @property
    def actions(self):
        return self.attempted_actions

    @property
    def effects(self):
        return self.confirmed_actions

    def __call__(self, identity, previous_reset_id, checkpoint, *, runtime_input_lock, occurrence_key):
        checkpoint()
        runtime_input_lock.assert_held(runtime_input_lock.owner, runtime_input_lock.invocation_id)
        self.calls.append((identity, previous_reset_id))
        self.occurrence_keys.append(occurrence_key)
        self.last_identity = identity
        if self.on_entry is not None:
            self.on_entry()
        try:
            result = self.adapter(
                identity, previous_reset_id, checkpoint,
                runtime_input_lock=runtime_input_lock, occurrence_key=occurrence_key,
            )
        except Exception as exc:
            partial = getattr(exc, "partial_result", None)
            self.last_result = dict(partial) if isinstance(partial, dict) else {}
            self._record_counts(self.last_result)
            raise
        self.last_result = self._result_mapping(result)
        self._record_counts(self.last_result)
        return result

    @staticmethod
    def _result_mapping(result):
        if isinstance(result, dict):
            return dict(result)
        consequence = getattr(result, "consequence", None)
        if isinstance(consequence, dict):
            native = consequence.get("native_result")
            return dict(native) if isinstance(native, dict) else dict(consequence)
        observed = getattr(result, "observed_progress", None)
        return dict(observed) if isinstance(observed, dict) else {}

    def _record_counts(self, result):
        attempted_fields = {
            HERO_DUEL_FLOW_ID: "duel_dispatch_count",
            RECOMMENDED_RESEARCH_FLOW_ID: "research_transport_calls",
            FOOD_FARM_BOOST_FLOW_ID: "food_farm_dispatch_count",
            HALL_OF_WAR_FLOW_ID: "hall_of_war_dispatch_count",
            TROOP_TRAINING_FLOW_ID: "training_dispatch_count",
            WALI_UPGRADE_FLOW_ID: "total_action_count",
        }
        committed = result.get("committed_action_count", 0)
        if self.flow_id == FOOD_FARM_BOOST_FLOW_ID:
            boost_action = result.get("boost_action")
            boost_confirmed = (
                isinstance(boost_action, dict) and boost_action.get("status") == "confirmed"
            )
            committed = int(result.get("collection_count", 0) == 1) + int(boost_confirmed)
        attempted = result.get(attempted_fields[self.flow_id], 0)
        self.attempted_actions = attempted if type(attempted) is int else 0
        self.confirmed_actions = committed if type(committed) is int else 0


def _hero_duel_result_builder(identity, stop, input_count, *, explicit_partial, interrupted, owner):
    result = _hero_duel_native_result(
        identity, input_count, observed_at=stop.now,
        attempted=explicit_partial, interrupted=interrupted,
    )
    if owner.duel_mode == "exhausted" and not explicit_partial and not interrupted:
        result.update(
            status="deferred", reason="free_entries_exhausted_without_canonical_cycles",
            initial_free_entries_remaining=0, ui_inferred_prior_uses=3,
            expected_defense_hero_ids=[], defense_save_confirmed=False,
            selected_listed_opponents=[], duel_dispatch_count=0, entry_transport_calls=0,
            flee_transport_calls=0, defense_save_transport_calls=0,
            defense_selection_transport_calls=0, flee_confirmed_count=0,
            committed_action_count=0, canonical_confirmed_cycle_ordinals=[], cycle_proofs=[],
            no_work=True,
        )
    return result


def _research_result_builder(identity, stop, input_count, *, explicit_partial, interrupted, owner):
    mode = (
        "unresolved" if explicit_partial else "blocked" if interrupted
        else "already_complete" if identity.reset_id in owner.completed_resets
        else owner.research_mode
    )
    result = _research_native_result(stop, identity, input_count, mode=mode)
    if mode == "completed":
        owner.completed_resets.add(identity.reset_id)
    return result


def _food_farm_result_builder(identity, stop, input_count, *, explicit_partial, interrupted, owner):
    reset_id = identity.reset_id
    occurrence_key = owner.current_occurrence_key
    if explicit_partial:
        owner.collection_unresolved_resets.add(reset_id)
        return _food_farm_native_result(
            identity, occurrence_key, input_count, mode="unresolved",
            collection_attempted=True, collection_confirmed=False,
            boost_attempted=False, boost_confirmed=False,
        )
    if interrupted:
        return _food_farm_native_result(
            identity, occurrence_key, input_count, mode="blocked",
            collection_attempted=False, collection_confirmed=False,
            boost_attempted=False, boost_confirmed=False,
        )
    if reset_id in owner.collection_unresolved_resets:
        return _food_farm_native_result(
            identity, occurrence_key, input_count, mode="collection_replay_blocked",
            collection_attempted=False, collection_confirmed=False,
            boost_attempted=False, boost_confirmed=False,
        )
    if reset_id in owner.boost_unresolved_resets:
        return _food_farm_native_result(
            identity, occurrence_key, input_count, mode="boost_replay_blocked",
            collection_attempted=False, collection_confirmed=True,
            boost_attempted=False, boost_confirmed=False,
            collection_collected=owner.collection_credit_by_reset.get(reset_id, False),
        )
    if reset_id in owner.boost_completed_resets:
        return _food_farm_native_result(
            identity, occurrence_key, input_count, mode="already_complete",
            collection_attempted=False, collection_confirmed=True,
            boost_attempted=False, boost_confirmed=False,
            collection_collected=owner.collection_credit_by_reset.get(reset_id, False),
        )
    if owner.collection_already_confirmed and owner.collection_confirmation_reset_id is None:
        owner.collection_confirmation_reset_id = reset_id
        owner.collection_confirmed_resets.add(reset_id)
        owner.collection_credit_by_reset[reset_id] = True
    collection_confirmed = reset_id in owner.collection_confirmed_resets
    mode = owner.farm_mode
    if mode == "already_active":
        return _food_farm_native_result(
            identity, occurrence_key, input_count, mode=mode,
            collection_attempted=False, collection_confirmed=False,
            boost_attempted=False, boost_confirmed=False,
        )
    collection_attempted = not collection_confirmed
    if mode == "boost_unresolved":
        result = _food_farm_native_result(
            identity, occurrence_key, input_count, mode=mode,
            collection_attempted=collection_attempted, collection_confirmed=True,
            boost_attempted=True, boost_confirmed=False,
        )
        owner.collection_credit_by_reset[reset_id] = bool(result["collection_count"])
        owner.collection_confirmed_resets.add(reset_id)
        owner.collection_confirmation_reset_id = reset_id
        owner.collection_already_confirmed = True
        owner.boost_unresolved_resets.add(reset_id)
        return result
    if mode == "diamond_guard":
        result = _food_farm_native_result(
            identity, occurrence_key, input_count, mode=mode,
            collection_attempted=collection_attempted, collection_confirmed=True,
            boost_attempted=False, boost_confirmed=False,
        )
        owner.collection_credit_by_reset[reset_id] = bool(result["collection_count"])
        owner.collection_confirmed_resets.add(reset_id)
        owner.collection_confirmation_reset_id = reset_id
        owner.collection_already_confirmed = True
        return result
    result = _food_farm_native_result(
        identity, occurrence_key, input_count, mode=mode,
        collection_attempted=collection_attempted, collection_confirmed=True,
        boost_attempted=True, boost_confirmed=True,
        collection_collected=(
            owner.collection_credit_by_reset[reset_id] if collection_confirmed else None
        ),
    )
    owner.collection_credit_by_reset[reset_id] = bool(result["collection_count"])
    owner.collection_confirmed_resets.add(reset_id)
    owner.collection_confirmation_reset_id = reset_id
    owner.collection_already_confirmed = True
    owner.boost_completed_resets.add(reset_id)
    return result


class GuardedHeroDuelRunner(_GuardedEAdapterRunner):
    def __init__(self, stop, output_directory):
        super().__init__(
            stop, output_directory, HERO_DUEL_FLOW_ID, 20, 11,
            HERO_DUEL_MAX_INPUTS, _hero_duel_result_builder,
            lambda native: HeroDuelRunner(
                native=native, output_directory=output_directory,
                serial=BLUESTACKS_SERIAL, utc_clock=lambda: stop.now,
            ),
        )
        self.duel_mode = "completed"


class GuardedRecommendedResearchRunner(_GuardedEAdapterRunner):
    def __init__(self, stop, output_directory):
        super().__init__(
            stop, output_directory, RECOMMENDED_RESEARCH_FLOW_ID, 5, 8,
            RECOMMENDED_RESEARCH_MAX_INPUTS, _research_result_builder,
            lambda native: RecommendedResearchRunner(
                native=native, output_directory=output_directory,
                serial=BLUESTACKS_SERIAL, utc_clock=lambda: stop.now,
            ),
        )
        self.research_mode = "completed"
        self.completed_resets = set()


class GuardedFoodFarmBoostRunner(_GuardedEAdapterRunner):
    def __init__(self, stop, output_directory):
        super().__init__(
            stop, output_directory, FOOD_FARM_BOOST_FLOW_ID, 4, 3,
            FOOD_FARM_BOOST_MAX_INPUTS, _food_farm_result_builder,
            lambda native: FoodFarmBoostRunner(
                native=native, output_directory=output_directory,
                serial=BLUESTACKS_SERIAL, utc_clock=lambda: stop.now,
            ),
        )
        self.farm_mode = "completed"
        self.collection_already_confirmed = False
        self.collection_confirmed_resets = set()
        self.collection_credit_by_reset = {}
        self.collection_confirmation_reset_id = None
        self.collection_unresolved_resets = set()
        self.boost_unresolved_resets = set()
        self.boost_completed_resets = set()
_HALL_HOME_FRAME = {"frame_path": "frames/hall-of-war-home.png", "frame_sha256": "a" * 64}


def _hall_backend_identity_proof(identity, stop):
    backend = derive_resource_runtime_identity(
        resource_fixed_runtime_binding(),
        datetime.fromtimestamp(float(stop.now), timezone.utc),
    )
    if (backend.account_id, backend.server_id) != (identity.account_id, identity.server_id):
        raise ValueError("fake Hall of War backend identity differs from scheduler identity")
    return {
        "runtime_scope": backend.runtime_scope,
        "account_id": backend.account_id,
        "server_id": backend.server_id,
        "reset_id": backend.reset_id,
        "reset_start_utc": backend.reset_start_utc,
        "reset_deadline_utc": backend.reset_deadline_utc,
        "assurance": backend.assurance.value,
        "runtime_binding_digest": backend.runtime_binding_digest,
    }


def _hall_of_war_native_result(identity, stop, input_count: int, *, mode: str):
    proof = _hall_backend_identity_proof(identity, stop)
    result = {
        "flow_id": HALL_OF_WAR_FLOW_ID,
        "product_id": HALL_OF_WAR_PRODUCT_ID,
        "product_revision": HALL_OF_WAR_PRODUCT_REVISION,
        "runtime_profile_id": HALL_OF_WAR_PROFILE_ID,
        "status": "complete_for_reset",
        "reason": "hall_of_war_challenge_and_reward_reconciled",
        "challenge_status": "confirmed",
        "reward_status": "claimed",
        "challenge_participation_proven": True,
        "saved_military_verified": True,
        "military_preset_verification": {
            "status": "already_applied",
            "preset_name": "Military",
            "verified": True,
            "switch_transport_attempted": False,
        },
        "troop_set_one": {
            "selected": True,
            "applied_toast_verified": True,
            "hero_count": 5,
            "current_troops": 160_200,
            "troop_capacity": None,
            "source_frame_sha256": "b" * 64,
        },
        "challenge_attempt_state": "ready",
        "today_highest_damage": 2_166_282_036,
        "challenge_transport_calls": 1,
        "dispatch_transport_calls": 1,
        "reward_claim_transport_calls": 1,
        "talent_switch_transport_calls": 0,
        "dispatch_action": {"status": "confirmed", "semantic_action": "HALL_OF_WAR_DISPATCH"},
        "reward_action": {"status": "confirmed", "semantic_action": "HALL_OF_WAR_REWARD"},
        "reward_action_key": "hall-of-war:reward:current-reset",
        "reward_result_frame": {"frame_path": "frames/hall-reward-claimed.png", "frame_sha256": "c" * 64},
        "hall_of_war_dispatch_count": 2,
        "committed_action_count": 2,
        "scheduler_reset_id": identity.reset_id,
        "backend_reset_id": proof["reset_id"],
        "backend_identity_proof": proof,
        "terminal_home_verified": True,
        "terminal_home_frame": dict(_HALL_HOME_FRAME),
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "accounting_verified": True,
        "total_input_count": input_count,
        "input_count": input_count,
        "verified_navigation": [
            "open-building",
            "open-zombie-zero",
            "select-troop-set-one",
            "confirm-result",
            "return-home",
        ],
    }
    if mode == "switched":
        result["military_preset_verification"].update(
            status="switched",
            switch_transport_attempted=True,
            switch_action_key="commander-talent-switch:military:offline-hall-of-war",
        )
        result.update(
            talent_switch_transport_calls=1,
            hall_of_war_dispatch_count=3,
            committed_action_count=3,
        )
    elif mode == "unresolved_dispatch":
        result.update(
            status="unresolved",
            reason="dispatch_effect_unresolved",
            challenge_status="unknown",
            reward_status="unknown",
            challenge_transport_calls=1,
            dispatch_transport_calls=1,
            reward_claim_transport_calls=0,
            dispatch_action={"status": "unresolved", "semantic_action": "HALL_OF_WAR_DISPATCH"},
            reward_action=None,
            hall_of_war_dispatch_count=1,
            committed_action_count=0,
            terminal_home_verified=False,
            terminal_home_frame=None,
            effect_reconciliation_required=True,
            identical_retry_denied=True,
        )
    elif mode == "blocked":
        result.update(
            status="blocked",
            reason="native checkpoint stopped before any consequential action",
            challenge_status="unknown",
            reward_status="unknown",
            challenge_transport_calls=0,
            dispatch_transport_calls=0,
            reward_claim_transport_calls=0,
            dispatch_action=None,
            reward_action=None,
            hall_of_war_dispatch_count=0,
            committed_action_count=0,
            terminal_home_verified=False,
            terminal_home_frame=None,
        )
    elif mode == "unavailable":
        result.update(
            status="deferred",
            reason="challenge_unavailable_and_daily_reward_unavailable",
            challenge_status="unavailable",
            reward_status="unavailable",
            challenge_participation_proven=False,
            challenge_attempt_state="unavailable",
            challenge_transport_calls=0,
            dispatch_transport_calls=0,
            reward_claim_transport_calls=0,
            dispatch_action=None,
            reward_action=None,
            hall_of_war_dispatch_count=0,
            committed_action_count=0,
            identical_retry_denied=False,
        )
    elif mode == "reward_unavailable":
        result.update(
            status="deferred",
            reason="daily_reward_not_available_after_confirmed_challenge",
            reward_status="unavailable",
            reward_claim_transport_calls=0,
            reward_action=None,
            hall_of_war_dispatch_count=1,
            committed_action_count=1,
            identical_retry_denied=False,
        )
    elif mode == "manual_prior_use":
        result.update(
            status="blocked",
            reason="prior_same_reset_use_has_no_canonical_dispatch_record",
            challenge_status="deferred_unexplained_prior_same_reset_use",
            challenge_participation_proven=True,
            challenge_transport_calls=0,
            dispatch_transport_calls=0,
            reward_status="already_claimed",
            reward_claim_transport_calls=0,
            dispatch_action=None,
            reward_action=None,
            hall_of_war_dispatch_count=0,
            committed_action_count=0,
            challenge_attempt_state="unavailable",
            identical_retry_denied=False,
        )
    elif mode == "already_reconciled":
        result.update(
            challenge_status="confirmed_prior_canonical_action",
            challenge_transport_calls=0,
            dispatch_transport_calls=0,
            reward_status="already_claimed",
            reward_claim_transport_calls=0,
            dispatch_action=None,
            reward_action=None,
            hall_of_war_dispatch_count=0,
            committed_action_count=0,
        )
    if result["status"] == "complete_for_reset" and result["dispatch_action"] is not None:
        result["dispatch_action"]["action_key"] = "hall-of-war:dispatch:current-reset"
    return result


def _hall_of_war_result_builder(identity, stop, input_count, *, explicit_partial, interrupted, owner):
    mode = "unresolved_dispatch" if explicit_partial else "blocked" if interrupted else owner.hall_mode
    return _hall_of_war_native_result(identity, stop, input_count, mode=mode)


def _training_current_maximum(identity, troop_type: str) -> int:
    digest = hashlib.sha256(f"{identity.reset_id}\0{troop_type}".encode("utf-8")).digest()
    return 601 + int.from_bytes(digest[:2], "big") % 300


def _training_variant_row(identity, stop, troop_type: str, *, queue_state: str = "active"):
    profile = default_troop_training_config()
    config = profile.for_type(troop_type)
    maximum = _training_current_maximum(identity, troop_type)
    quantity = maximum if config.quantity_mode == "current_max" else config.quantity
    assert quantity is not None
    tier = config.target_tier
    assert tier is not None
    action_key = make_training_start_action_key(
        training_identity_digest(FIXED_RUNTIME_SCOPE, identity.account_id, identity.server_id),
        identity.reset_id,
        troop_type,
        1,
    )
    expected_completion = datetime.fromtimestamp(float(stop.now), timezone.utc) + timedelta(seconds=3_600)
    requirements = {
        "food": quantity * 12,
        "wood": quantity * 8,
        "steel": quantity * 4,
        "gas": quantity * 2,
    }
    before = [
        asdict(ResourceReading(name, amount + 20_000, amount))
        for name, amount in requirements.items()
    ]
    after = [
        asdict(ResourceReading(name, amount + 20_000 - amount, amount))
        for name, amount in requirements.items()
    ]
    return {
        "troop_type": troop_type,
        "facility_identity": FACILITY_BY_TYPE[troop_type],
        "selected_tier": tier,
        "quantity": quantity,
        "configured_quantity": config.quantity,
        "quantity_mode": config.quantity_mode,
        "quantity_maximum": maximum,
        "maximum_equality_proven": (
            config.quantity_mode != "current_max" or quantity == maximum
        ),
        "queue_label": f"{troop_type.title()} T{tier}",
        "queue_troop_type": troop_type,
        "queue_tier": tier,
        "queue_quantity": quantity,
        "duration_source": "queue_band",
        "queue_spatially_associated": True,
        "resources_before": before,
        "resources_after": after,
        "reset_identity": identity.reset_id,
        "action_key": action_key,
        "queue_generation": 1,
        "source_frame_hash": "d" * 64,
        "immediate_before_frame_hash": "d" * 64,
        "immediate_post_frame_hash": "e" * 64,
        "displayed_training_duration_seconds": 3_600,
        "dispatch_timestamp": datetime.fromtimestamp(float(stop.now), timezone.utc).isoformat(),
        "expected_completion_timestamp": expected_completion.isoformat(),
        "queue_state": queue_state,
        "training_policy": config.training_policy,
        "next_eligible_timestamp": (
            None if config.training_policy == "continuous"
            else (
                datetime.fromtimestamp(float(stop.now), timezone.utc)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)
            ).isoformat()
        ),
    }


def _training_resolved_config(identity, *, started: set[str]):
    profile = default_troop_training_config()
    resolved = profile.resolved_profile()
    for troop_type in TROOP_TYPES:
        config = profile.for_type(troop_type)
        maximum = _training_current_maximum(identity, troop_type)
        resolved[troop_type].update(
            resolved_quantity=maximum if config.quantity_mode == "current_max" else config.quantity,
            daily_initiation_state=(
                "initiated" if config.training_policy == "once_daily" and troop_type in started
                else "not_started"
            ),
            queue_state="active" if troop_type in started else "empty",
            queue_generation=1 if troop_type in started else 0,
            per_reset_variant_start_count=1 if troop_type in started else 0,
            per_reset_variant_claim_count=0,
            pending_start_action_key=(
                make_training_start_action_key(
                    training_identity_digest(FIXED_RUNTIME_SCOPE, identity.account_id, identity.server_id),
                    identity.reset_id, troop_type, 1,
                ) if troop_type in started else None
            ),
            next_start_action_key=None if troop_type in started else make_training_start_action_key(
                training_identity_digest(FIXED_RUNTIME_SCOPE, identity.account_id, identity.server_id),
                identity.reset_id, troop_type, 1,
            ),
        )
    return resolved


def _troop_training_native_result(identity, stop, input_count: int, *, mode: str):
    started_types = (
        set(TROOP_TYPES) if mode in {"completed", "occupied"}
        else {"fighter"} if mode == "unresolved"
        else set()
    )
    training_rows = [
        _training_variant_row(identity, stop, troop_type)
        for troop_type in TROOP_TYPES if troop_type in started_types
    ]
    reset_deadline = (int(float(stop.now) // 86_400) + 1) * 86_400
    result = {
        "flow_id": TROOP_TRAINING_FLOW_ID,
        "task_id": TROOP_TRAINING_PRODUCT_ID,
        "native_task_id": TROOP_TRAINING_FLOW_ID,
        "product_id": TROOP_TRAINING_PRODUCT_ID,
        "product_revision": TROOP_TRAINING_PRODUCT_REVISION,
        "runtime_profile_id": TROOP_TRAINING_PROFILE_ID,
        "status": "completed",
        "reason": "all configured training variants reconciled at canonical Home",
        "actions_completed": input_count,
        "completed_claims": [],
        "warehouse_approvals": [],
        "resource_box_approvals": [],
        "training": training_rows,
        "final_home_recognized": mode != "unresolved",
        "entry_navigation": {"canonical_home_entry_verified": True, "terminal_home_verified": mode != "unresolved"},
        "session": "service-route-contract/troop-training",
        "resolved_config": _training_resolved_config(identity, started=started_types),
        "training_dispatch_count": 4 if mode == "completed" else 0,
        "training_start_transport_calls": 4 if mode == "completed" else 0,
        "claim_dispatch_count": 0,
        "resource_box_dispatch_count": 0,
        "warehouse_dispatch_count": 0,
        "committed_action_count": 4 if mode == "completed" else 0,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "terminal_home_verified": mode != "unresolved",
        "saved_training_preset_verified": True,
        "remaining_eligible_variants": [],
        "accounting_verified": True,
        "total_input_count": input_count,
        "input_count": input_count,
        "native_execution_verified": True,
        "next_due_utc": float(stop.now) + 3_600,
    }
    if mode == "unresolved":
        result.update(
            status="unresolved",
            reason="training start successor unknown after a confirmed training-start prefix",
            training=training_rows[:1],
            training_dispatch_count=2,
            training_start_transport_calls=2,
            committed_action_count=1,
            effect_reconciliation_required=True,
            identical_retry_denied=True,
            terminal_home_verified=False,
            final_home_recognized=False,
            saved_training_preset_verified=True,
            remaining_eligible_variants=list(TROOP_TYPES[1:]),
            next_due_utc=None,
        )
    elif mode == "resource_shortage":
        result.update(
            status="deferred",
            reason="fighter exact base-resource shortage; no box/warehouse continuation authorized",
            training=[{
                "troop_type": "fighter",
                "queue_state": "empty",
                "status": "deferred_resource_shortage",
                "reason": "exact base resources insufficient; resource-box/warehouse continuation is not authorized",
            }],
            resolved_config=_training_resolved_config(identity, started=set()),
            next_due_utc=float(stop.now) + 300,
        )
    elif mode == "box_deferred":
        result.update(
            status="deferred",
            reason="evidence_required: exact resource-box identity/effect proof unavailable; continuation deferred",
            training=[{
                "troop_type": "fighter",
                "queue_state": "empty",
                "status": "deferred_resource_shortage",
                "reason": "resource-box continuation lacks exact inventory/effect authority",
            }],
            resolved_config=_training_resolved_config(identity, started=set()),
            next_due_utc=float(stop.now) + 300,
        )
    elif mode == "unavailable":
        result.update(
            status="deferred",
            reason="no eligible training queue action is currently available",
            training=[],
            resolved_config=_training_resolved_config(identity, started=set()),
            next_due_utc=float(reset_deadline),
        )
    elif mode == "occupied":
        result.update(
            status="deferred",
            reason="active queues are positively recognized; no duplicate start is dispatched",
            training_dispatch_count=0,
            training_start_transport_calls=0,
            committed_action_count=0,
            next_due_utc=float(stop.now) + 1_800,
        )
    return result


def _troop_training_result_builder(identity, stop, input_count, *, explicit_partial, interrupted, owner):
    if explicit_partial:
        mode = "unresolved"
    elif interrupted:
        mode = "unavailable"
    elif identity.reset_id in owner.completed_resets:
        mode = "occupied"
    else:
        mode = owner.training_mode
    result = _troop_training_native_result(identity, stop, input_count, mode=mode)
    if mode == "completed":
        owner.completed_resets.add(identity.reset_id)
        owner.prior_batches[identity.reset_id] = {
            row["troop_type"]: dict(row) for row in result["training"]
        }
    elif mode == "occupied":
        prior = owner.prior_batches.get(identity.reset_id, {})
        for row in result["training"]:
            troop_type = row["troop_type"]
            batch = prior.get(troop_type)
            if batch is None:
                continue
            row.update(
                quantity=batch["quantity"],
                queue_quantity=batch["quantity"],
                authorized_batch_quantity=batch["quantity"],
                quantity_maximum=row["quantity_maximum"] + owner.current_maximum_delta,
                completion_policy="read_only_existing_queue",
                resources_before=batch["resources_after"],
                resources_after=batch["resources_after"],
            )
            row.pop("dispatch_timestamp", None)
            row.pop("maximum_equality_proven", None)
            result["resolved_config"][troop_type]["resolved_quantity"] = batch["quantity"]
    return result


class GuardedHallOfWarRunner(_GuardedEAdapterRunner):
    def __init__(self, stop, output_directory):
        super().__init__(
            stop, output_directory, HALL_OF_WAR_ADAPTER_FLOW_ID, 18, 12,
            HALL_OF_WAR_ADAPTER_MAX_INPUTS, _hall_of_war_result_builder,
            lambda native: HallOfWarRunner(
                native=native, output_directory=output_directory,
                serial=BLUESTACKS_SERIAL, utc_clock=lambda: stop.now,
            ),
        )
        self.hall_mode = "completed"


class GuardedTroopTrainingRunner(_GuardedEAdapterRunner):
    def __init__(self, stop, output_directory):
        def adapter(native):
            native.product_id = TROOP_TRAINING_ADAPTER_PRODUCT_ID
            native.product_revision = TROOP_TRAINING_ADAPTER_PRODUCT_REVISION
            native.runtime_profile_id = TROOP_TRAINING_ADAPTER_PROFILE_ID
            native.max_inputs = TROOP_TRAINING_ADAPTER_MAX_INPUTS
            native.max_actions = TROOP_TRAINING_MAX_ACTIONS
            return TroopTrainingRunner(
                native=native, output_directory=output_directory,
                utc_clock=lambda: stop.now,
            )

        super().__init__(
            stop, output_directory, TROOP_TRAINING_ADAPTER_FLOW_ID, 28, 18,
            TROOP_TRAINING_ADAPTER_MAX_INPUTS, _troop_training_result_builder, adapter,
        )
        self.training_mode = "completed"
        self.completed_resets = set()
        self.prior_batches = {}
        self.current_maximum_delta = 0


def _wali_observation(game_day_id, *, level, cap, confirmed, balance, phase):
    """Synthetic semantic model, not a retained native capture."""
    return HeroUpgradeObservation(
        screen_state="HERO", hero_identity="Wali", hero_selected=True,
        current_level=level, evolution_cap=cap,
        material_costs={"ANTISERUM": 100}, material_balances={"ANTISERUM": balance},
        target_identity="hero-upgrade", target_roi=(100, 1140, 350, 1220),
        panel_bounds=(44, 100, 756, 1250), control_class="UPGRADE",
        game_day_id=game_day_id, confirmed_upgrades=confirmed,
        material_rows_complete=True, stable_selected_state=True,
        normal_upgrade_visible=True, normal_single_upgrade=True,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256=hashlib.sha256(phase.encode()).hexdigest(),
        evidence_refs=(f"synthetic:wali:{phase}",),
    )


def _wali_upgrade_result_builder(identity, stop, input_count, *, explicit_partial, interrupted, owner):
    prior = owner.confirmed_by_reset.get(identity.reset_id, 0)
    defer_prefix = owner.wali_mode == "deferred_prefix"
    count = 0 if interrupted else min(1, 3 - prior) if explicit_partial or defer_prefix else 3 - prior
    with_evolution = owner.wali_mode == "standard_evolution" and not explicit_partial and not interrupted and prior == 0
    batches, evolutions = [], []
    level, cap, balance = (9, 10, 1000) if with_evolution or explicit_partial else (5 + prior, 30, 1000)
    index = 0
    while index < count:
        ordinal = prior + index + 1
        input_limit = min(3 - prior - index, cap - level)
        batch_inputs = min(count - index, input_limit)
        key = f"wali:{identity.account_id}:{identity.server_id}:{identity.reset_id}:normal-batch:{ordinal}"
        before = _wali_observation(
            identity.reset_id, level=level, cap=cap, confirmed=ordinal - 1,
            balance=balance, phase=f"{key}:before",
        )
        level, balance = level + batch_inputs, balance - 100 * batch_inputs
        index += batch_inputs
        after = _wali_observation(
            identity.reset_id, level=level, cap=cap, confirmed=prior + index,
            balance=balance, phase=f"{key}:after",
        )
        batches.append({
            "action_key": key, "first_ordinal": ordinal, "input_limit": input_limit,
            "normal_inputs": batch_inputs, "quoted_antiserum_costs": [100] * batch_inputs,
            "before": asdict(before), "after": asdict(after), "semantic_verified": True,
        })
        if with_evolution and level == cap:
            evolution_key = f"wali:{identity.account_id}:{identity.server_id}:{identity.reset_id}:evolution:{cap}"
            evolution_before = replace(
                after, screen_state="HERO_EVOLUTION_PREVIEW", target_identity="hero-evolve",
                target_roi=(280, 900, 520, 980), control_class="EVOLVE",
                material_costs={"ANTISERUM": 200, "COMBAT_MANUAL_I": 30},
                material_balances={"ANTISERUM": balance, "COMBAT_MANUAL_I": 50},
                next_evolution_cap=30, normal_upgrade_visible=False, normal_single_upgrade=False,
                evolution_control_visible=True,
                source_frame_sha256=hashlib.sha256(f"{evolution_key}:before".encode()).hexdigest(),
                evidence_refs=(f"synthetic:wali:{evolution_key}:before",),
            )
            level, cap, balance = level + 1, 30, balance - 200
            evolution_after = replace(
                _wali_observation(
                    identity.reset_id, level=level, cap=cap, confirmed=ordinal,
                    balance=balance, phase=f"{evolution_key}:after",
                ),
                material_usage_receipts=("COMBAT_MANUAL_I",),
                evidence_refs=(f"synthetic:wali:{evolution_key}:usage-toast", f"synthetic:wali:{evolution_key}:settled"),
            )
            evolutions.append({
                "action_key": evolution_key, "before": asdict(evolution_before),
                "after": asdict(evolution_after), "semantic_verified": True,
            })
    committed = count + len(evolutions)
    attempts = committed + int(explicit_partial)
    if not interrupted:
        owner.confirmed_by_reset[identity.reset_id] = prior + count
    home = {"frame_path": "frames/wali-home.png", "frame_sha256": "c" * 64}
    return {
        "status": "unknown" if explicit_partial else "blocked" if interrupted else "deferred" if defer_prefix and prior + count < 3 else "completed",
        "reason": "synthetic_wali_unknown_successor" if explicit_partial else "synthetic_wali_partial_deferral" if defer_prefix else "synthetic_wali_route",
        "hero_identity": "Wali", "game_day_id": identity.reset_id,
        "occurrence_key": owner.current_occurrence_key,
        "prior_confirmed_upgrades": prior, "confirmed_upgrades": prior + count,
        "level_upgrade_committed_count": count, "evolution_committed_count": len(evolutions),
        "committed_action_count": committed,
        "upgrade_transport_calls": count,
        "evolution_transport_calls": len(evolutions) + int(explicit_partial), "total_action_count": attempts,
        "input_actions": input_count, "normal_batches": batches, "evolutions": evolutions,
        "unknown_action_sent": explicit_partial, "identical_retry_denied": explicit_partial,
        "terminal_home_verified": not interrupted and not explicit_partial,
        "terminal_home_frame": home, "terminal_home_frame_sha256": home["frame_sha256"],
        "evidence_refs": ("synthetic:wali:terminal",),
        "campaign_reset_evidence_required": True, "reset_transport_calls": 0, "reset_count_unchanged": True,
    }


class GuardedWaliUpgradeRunner(_GuardedEAdapterRunner):
    def __init__(self, stop, output_directory):
        super().__init__(
            stop, output_directory, WALI_UPGRADE_FLOW_ID, 12, 8,
            WALI_UPGRADE_MAX_INPUTS, _wali_upgrade_result_builder,
            lambda native: WaliUpgradeRunner(
                native=native, output_directory=output_directory, utc_clock=lambda: stop.now,
            ),
        )
        self.wali_mode = "single_upgrades"
        self.confirmed_by_reset: dict[str, int] = {}
