"""Legacy production-registration records retained for compatibility.

Canonical scheduler admission is persisted in ``BotStateManager``.  The
consume-once helpers below remain available only to not-yet-migrated routes;
they are never consulted by the new scheduler/service path.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Iterator, Mapping

from .contracts import FlowDescriptor, FlowSpec, RecurrenceClass, RecurrenceProjection
from tasks.campaign_auto_battle import CAMPAIGN_MAX_INPUTS
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "tasks"
    / "flow_delivery_disabled_production_registry.json"
)
WORLD_FLOW_ID = "WORLD-MAP-NAVIGATION-FOUNDATION"
WORLD_PRODUCT_ID = "world_map_navigation"
WORLD_PRODUCT_REVISION = "world_map_navigation-v1"
WORLD_HANDLER_ID = "world_map_navigation_foundation_selection_handler"
WORLD_PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
WORLD_PHASE_MODE = "phase_canary"
# Explicit aliases keep the fixed binding easy to consume without introducing
# a second registration vocabulary.
WORLD_SELECTION_HANDLER_ID = WORLD_HANDLER_ID
WORLD_PROFILE = WORLD_PROFILE_ID
WORLD_PRODUCT = WORLD_PRODUCT_ID
WORLD_REVISION = WORLD_PRODUCT_REVISION
NOVA_FLOW_ID = "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE"
NOVA_PRODUCT_ID = "nova_praise"
NOVA_PRODUCT_REVISION = "nova_praise-v1"
NOVA_HANDLER_ID = "nova_praise_selection_handler"
NOVA_PROFILE_ID = WORLD_PROFILE_ID
NOVA_PHASE_MODE = "phase_canary"
NOVA_MAX_INPUTS = 8
# Explicit aliases keep the fixed binding easy to consume without introducing
# a second registration vocabulary.
NOVA_SELECTION_HANDLER_ID = NOVA_HANDLER_ID
NOVA_PROFILE = NOVA_PROFILE_ID
NOVA_PRODUCT = NOVA_PRODUCT_ID
NOVA_REVISION = NOVA_PRODUCT_REVISION
RECRUITMENT_FLOW_ID = "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE"
RECRUITMENT_PRODUCT_ID = "noahs_tavern_recruitment"
RECRUITMENT_PRODUCT_REVISION = "noahs_tavern_recruitment-v1"
RECRUITMENT_HANDLER_ID = "recruitment_maintenance_selection_handler"
RECRUITMENT_PROFILE_ID = WORLD_PROFILE_ID
RECRUITMENT_PHASE_MODE = "phase_canary"
RECRUITMENT_MAX_INPUTS = 12
RECRUITMENT_SELECTION_HANDLER_ID = RECRUITMENT_HANDLER_ID
RECRUITMENT_PROFILE = RECRUITMENT_PROFILE_ID
RECRUITMENT_PRODUCT = RECRUITMENT_PRODUCT_ID
RECRUITMENT_REVISION = RECRUITMENT_PRODUCT_REVISION
CAMPAIGN_FLOW_ID = "CAMPAIGN-AP-AUTO-BATTLE"
CAMPAIGN_PRODUCT_ID = "campaign_ap"
CAMPAIGN_PRODUCT_REVISION = "campaign_ap-v1"
CAMPAIGN_HANDLER_ID = "campaign_ap_selection_handler"
CAMPAIGN_PROFILE_ID = WORLD_PROFILE_ID
CAMPAIGN_PHASE_MODE = "phase_canary"
CAMPAIGN_ROUTE_MAX_INPUTS = CAMPAIGN_MAX_INPUTS
CAMPAIGN_SELECTION_HANDLER_ID = CAMPAIGN_HANDLER_ID
CAMPAIGN_PROFILE = CAMPAIGN_PROFILE_ID
CAMPAIGN_PRODUCT = CAMPAIGN_PRODUCT_ID
CAMPAIGN_REVISION = CAMPAIGN_PRODUCT_REVISION
BIOENHANCER_FLOW_ID = "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION"
BIOENHANCER_PRODUCT_ID = "bioenhancer_research"
BIOENHANCER_PRODUCT_REVISION = "bioenhancer_research-v1"
BIOENHANCER_HANDLER_ID = "bioenhancer_research_execution_handler"
BIOENHANCER_PROFILE_ID = WORLD_PROFILE_ID
BIOENHANCER_PHASE_MODE = "phase_canary"
BIOENHANCER_MAX_INPUTS = 8
SUPPLY_FLOW_ID = "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION"
SUPPLY_PRODUCT_ID = "supply_depot"
SUPPLY_PRODUCT_REVISION = "supply_depot-v2"
SUPPLY_HANDLER_ID = "supply_depot_execution_handler"
SUPPLY_PROFILE_ID = WORLD_PROFILE_ID
SUPPLY_PHASE_MODE = "phase_canary"
SUPPLY_MAX_INPUTS = 10
ULTIMATE_FLOW_ID = "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
ULTIMATE_PRODUCT_ID = "ultimate_challenge_daily"
ULTIMATE_PRODUCT_REVISION = "ultimate_challenge_daily-v1"
ULTIMATE_HANDLER_ID = "ultimate_challenge_daily_execution_handler"
ULTIMATE_PROFILE_ID = WORLD_PROFILE_ID
ULTIMATE_PHASE_MODE = "phase_canary"
ULTIMATE_MAX_INPUTS = 16
ENHANCEMENT_FLOW_ID = "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION"
ENHANCEMENT_PRODUCT_ID = "enhancement_family"
ENHANCEMENT_PRODUCT_REVISION = "enhancement_family-v1"
ENHANCEMENT_HANDLER_ID = "enhancement_family_execution_handler"
ENHANCEMENT_PROFILE_ID = WORLD_PROFILE_ID
ENHANCEMENT_PHASE_MODE = "phase_canary"
ENHANCEMENT_MAX_INPUTS = 24
PERSONAL_MIGHT_FLOW_ID = "PERSONAL-MIGHT-PRAISE-BLUESTACKS-INTEGRATION"
PERSONAL_MIGHT_PRODUCT_ID = "personal_might_praise"
PERSONAL_MIGHT_PRODUCT_REVISION = "personal_might_praise-v1"
PERSONAL_MIGHT_HANDLER_ID = "personal_might_praise_execution_handler"
PERSONAL_MIGHT_PROFILE_ID = WORLD_PROFILE_ID
PERSONAL_MIGHT_PHASE_MODE = "phase_canary"
PERSONAL_MIGHT_MAX_INPUTS = 8
DAILY_REWARDS_FLOW_ID = "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"
DAILY_REWARDS_PRODUCT_ID = "aggregate_daily_claim"
DAILY_REWARDS_PRODUCT_REVISION = "aggregate_daily_claim-v3"
DAILY_REWARDS_HANDLER_ID = "daily_rewards_execution_handler"
DAILY_REWARDS_PROFILE_ID = WORLD_PROFILE_ID
DAILY_REWARDS_PHASE_MODE = "phase_canary"
DAILY_REWARDS_MAX_INPUTS = 16
RESOURCE_ITEM_FLOW_ID = "DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION"
RESOURCE_ITEM_PRODUCT_ID = "use_resource_item"
RESOURCE_ITEM_PRODUCT_REVISION = "use_resource_item-v3"
RESOURCE_ITEM_HANDLER_ID = "resource_item_execution_handler"
RESOURCE_ITEM_PROFILE_ID = WORLD_PROFILE_ID
RESOURCE_ITEM_PHASE_MODE = "phase_canary"
RESOURCE_ITEM_MAX_INPUTS = 10
RUINS_FLOW_ID = "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
RUINS_PRODUCT_ID = "ruins_challenge"
RUINS_PRODUCT_REVISION = "ruins_challenge-v2"
RUINS_HANDLER_ID = "ruins_execution_handler"
RUINS_PROFILE_ID = WORLD_PROFILE_ID
RUINS_PHASE_MODE = "phase_canary"
RUINS_MAX_INPUTS = 48
ALLIANCE_HELP_FLOW_ID = "ALLIANCE-HELP-TEN-FREE-REQUESTS"
ALLIANCE_HELP_PRODUCT_ID = "alliance_help"
ALLIANCE_HELP_PRODUCT_REVISION = "alliance_help-v2"
ALLIANCE_HELP_HANDLER_ID = "alliance_help_execution_handler"
ALLIANCE_HELP_PROFILE_ID = WORLD_PROFILE_ID
ALLIANCE_HELP_PHASE_MODE = "phase_canary"
ALLIANCE_HELP_MAX_INPUTS = 20
ALLIANCE_DONATION_FLOW_ID = "ALLIANCE-TECH-DONATION-BLUESTACKS-INTEGRATION"
ALLIANCE_DONATION_PRODUCT_ID = "alliance_donation"
ALLIANCE_DONATION_PRODUCT_REVISION = "alliance_donation-v2"
ALLIANCE_DONATION_HANDLER_ID = "alliance_donation_execution_handler"
ALLIANCE_DONATION_PROFILE_ID = WORLD_PROFILE_ID
ALLIANCE_DONATION_PHASE_MODE = "phase_canary"
ALLIANCE_DONATION_MAX_INPUTS = 40
ALLIANCE_SHOP_FLOW_ID = "ALLIANCE-SHOP-PURCHASE-EVIDENCE-GATE"
ALLIANCE_SHOP_PRODUCT_ID = "alliance_shop_purchase"
ALLIANCE_SHOP_PRODUCT_REVISION = "alliance_shop_purchase-v3"
ALLIANCE_SHOP_HANDLER_ID = "alliance_shop_execution_handler"
ALLIANCE_SHOP_PROFILE_ID = WORLD_PROFILE_ID
ALLIANCE_SHOP_PHASE_MODE = "phase_canary"
ALLIANCE_SHOP_MAX_INPUTS = 24
DAILY_SHOPS_FLOW_ID = "DAILY-SHOPS-PURCHASE-EVIDENCE-GATE"
DAILY_SHOPS_PRODUCT_ID = "daily_shops_purchase"
DAILY_SHOPS_PRODUCT_REVISION = "daily_shops_purchase-v2"
DAILY_SHOPS_HANDLER_ID = "daily_shops_execution_handler"
DAILY_SHOPS_PROFILE_ID = WORLD_PROFILE_ID
DAILY_SHOPS_PHASE_MODE = "phase_canary"
DAILY_SHOPS_MAX_INPUTS = 48

NANO_MATERIAL_PRODUCTION_FLOW_ID = "NANO-MATERIAL-PRODUCTION-MAINTENANCE"
NANO_MATERIAL_PRODUCTION_PRODUCT_ID = "nano_material_production"
NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION = "nano_material_production-v2"
NANO_MATERIAL_PRODUCTION_HANDLER_ID = "nano_material_production_execution_handler"
NANO_MATERIAL_PRODUCTION_PROFILE_ID = WORLD_PROFILE_ID
NANO_MATERIAL_PRODUCTION_PHASE_MODE = "phase_canary"
NANO_MATERIAL_PRODUCTION_MAX_INPUTS = 18
NANOWEAPON_FLOW_ID = "NANOWEAPON-BLUESTACKS-INTEGRATION"
NANOWEAPON_PRODUCT_ID = "nanoweapon_normal_craft"
NANOWEAPON_PRODUCT_REVISION = "nanoweapon_normal_craft-v3"
NANOWEAPON_HANDLER_ID = "nanoweapon_execution_handler"
NANOWEAPON_PROFILE_ID = WORLD_PROFILE_ID
NANOWEAPON_PHASE_MODE = "phase_canary"
NANOWEAPON_MAX_INPUTS = 22
HERO_DUEL_FLOW_ID = "HERO-DUEL-EVIDENCE-GATE"
HERO_DUEL_PRODUCT_ID = "hero_duel"
HERO_DUEL_PRODUCT_REVISION = "hero_duel-v3"
HERO_DUEL_HANDLER_ID = "hero_duel_execution_handler"
HERO_DUEL_PROFILE_ID = WORLD_PROFILE_ID
HERO_DUEL_PHASE_MODE = "phase_canary"
HERO_DUEL_MAX_INPUTS = 64
RECOMMENDED_RESEARCH_FLOW_ID = "RECOMMENDED-RESEARCH-BLUESTACKS-INTEGRATION"
RECOMMENDED_RESEARCH_PRODUCT_ID = "recommended_research"
RECOMMENDED_RESEARCH_PRODUCT_REVISION = "recommended_research-v2"
RECOMMENDED_RESEARCH_HANDLER_ID = "recommended_research_execution_handler"
RECOMMENDED_RESEARCH_PROFILE_ID = WORLD_PROFILE_ID
RECOMMENDED_RESEARCH_PHASE_MODE = "phase_canary"
RECOMMENDED_RESEARCH_MAX_INPUTS = 24
FOOD_FARM_BOOST_FLOW_ID = "FOOD-FARM-OUTPUT-BOOST-DAILY-BLUESTACKS-INTEGRATION"
FOOD_FARM_BOOST_PRODUCT_ID = "food_farm_output_boost"
FOOD_FARM_BOOST_PRODUCT_REVISION = "food_farm_output_boost-v2"
FOOD_FARM_BOOST_HANDLER_ID = "food_farm_boost_execution_handler"
FOOD_FARM_BOOST_PROFILE_ID = WORLD_PROFILE_ID
FOOD_FARM_BOOST_PHASE_MODE = "phase_canary"
FOOD_FARM_BOOST_MAX_INPUTS = 16
HALL_OF_WAR_FLOW_ID = "HALL-OF-WAR-ZOMBIE-ZERO-BLUESTACKS-INTEGRATION"
HALL_OF_WAR_PRODUCT_ID = "hall_of_war_zombie_zero"
HALL_OF_WAR_PRODUCT_REVISION = "hall_of_war_zombie_zero-v1"
HALL_OF_WAR_HANDLER_ID = "hall_of_war_execution_handler"
HALL_OF_WAR_PROFILE_ID = WORLD_PROFILE_ID
HALL_OF_WAR_PHASE_MODE = "phase_canary"
HALL_OF_WAR_MAX_INPUTS = 24
TROOP_TRAINING_FLOW_ID = "TROOP-TRAINING-END-TO-END-CONSOLIDATION"
TROOP_TRAINING_PRODUCT_ID = "troop_training"
TROOP_TRAINING_PRODUCT_REVISION = "troop_training-v3"
TROOP_TRAINING_HANDLER_ID = "troop_training_execution_handler"
TROOP_TRAINING_PROFILE_ID = WORLD_PROFILE_ID
TROOP_TRAINING_PHASE_MODE = "phase_canary"
TROOP_TRAINING_MAX_INPUTS = 96
WALI_UPGRADE_FLOW_ID = "HERO-UPGRADE-EVIDENCE-GATE"
WALI_UPGRADE_PRODUCT_ID = "hero_upgrade"
WALI_UPGRADE_PRODUCT_REVISION = "hero_upgrade-v4"
WALI_UPGRADE_HANDLER_ID = "wali_upgrade_execution_handler"
WALI_UPGRADE_PROFILE_ID = WORLD_PROFILE_ID
WALI_UPGRADE_PHASE_MODE = "phase_canary"
WALI_UPGRADE_MAX_INPUTS = 48


_FIXED_BINDINGS = {
    WORLD_FLOW_ID: {
        "flow_id": WORLD_FLOW_ID,
        "product_id": WORLD_PRODUCT_ID,
        "product_revision": WORLD_PRODUCT_REVISION,
        "production_handler": WORLD_HANDLER_ID,
        "profile": WORLD_PROFILE_ID,
        "mode": WORLD_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    NOVA_FLOW_ID: {
        "flow_id": NOVA_FLOW_ID,
        "product_id": NOVA_PRODUCT_ID,
        "product_revision": NOVA_PRODUCT_REVISION,
        "production_handler": NOVA_HANDLER_ID,
        "profile": NOVA_PROFILE_ID,
        "mode": NOVA_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    RECRUITMENT_FLOW_ID: {
        "flow_id": RECRUITMENT_FLOW_ID,
        "product_id": RECRUITMENT_PRODUCT_ID,
        "product_revision": RECRUITMENT_PRODUCT_REVISION,
        "production_handler": RECRUITMENT_HANDLER_ID,
        "profile": RECRUITMENT_PROFILE_ID,
        "mode": RECRUITMENT_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    CAMPAIGN_FLOW_ID: {
        "flow_id": CAMPAIGN_FLOW_ID,
        "product_id": CAMPAIGN_PRODUCT_ID,
        "product_revision": CAMPAIGN_PRODUCT_REVISION,
        "production_handler": CAMPAIGN_HANDLER_ID,
        "profile": CAMPAIGN_PROFILE_ID,
        "mode": CAMPAIGN_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    BIOENHANCER_FLOW_ID: {
        "flow_id": BIOENHANCER_FLOW_ID,
        "product_id": BIOENHANCER_PRODUCT_ID,
        "product_revision": BIOENHANCER_PRODUCT_REVISION,
        "production_handler": BIOENHANCER_HANDLER_ID,
        "profile": BIOENHANCER_PROFILE_ID,
        "mode": BIOENHANCER_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    SUPPLY_FLOW_ID: {
        "flow_id": SUPPLY_FLOW_ID,
        "product_id": SUPPLY_PRODUCT_ID,
        "product_revision": SUPPLY_PRODUCT_REVISION,
        "production_handler": SUPPLY_HANDLER_ID,
        "profile": SUPPLY_PROFILE_ID,
        "mode": SUPPLY_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    ULTIMATE_FLOW_ID: {
        "flow_id": ULTIMATE_FLOW_ID,
        "product_id": ULTIMATE_PRODUCT_ID,
        "product_revision": ULTIMATE_PRODUCT_REVISION,
        "production_handler": ULTIMATE_HANDLER_ID,
        "profile": ULTIMATE_PROFILE_ID,
        "mode": ULTIMATE_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    ENHANCEMENT_FLOW_ID: {
        "flow_id": ENHANCEMENT_FLOW_ID,
        "product_id": ENHANCEMENT_PRODUCT_ID,
        "product_revision": ENHANCEMENT_PRODUCT_REVISION,
        "production_handler": ENHANCEMENT_HANDLER_ID,
        "profile": ENHANCEMENT_PROFILE_ID,
        "mode": ENHANCEMENT_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    PERSONAL_MIGHT_FLOW_ID: {
        "flow_id": PERSONAL_MIGHT_FLOW_ID,
        "product_id": PERSONAL_MIGHT_PRODUCT_ID,
        "product_revision": PERSONAL_MIGHT_PRODUCT_REVISION,
        "production_handler": PERSONAL_MIGHT_HANDLER_ID,
        "profile": PERSONAL_MIGHT_PROFILE_ID,
        "mode": PERSONAL_MIGHT_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    DAILY_REWARDS_FLOW_ID: {
        "flow_id": DAILY_REWARDS_FLOW_ID,
        "product_id": DAILY_REWARDS_PRODUCT_ID,
        "product_revision": DAILY_REWARDS_PRODUCT_REVISION,
        "production_handler": DAILY_REWARDS_HANDLER_ID,
        "profile": DAILY_REWARDS_PROFILE_ID,
        "mode": DAILY_REWARDS_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    RESOURCE_ITEM_FLOW_ID: {
        "flow_id": RESOURCE_ITEM_FLOW_ID,
        "product_id": RESOURCE_ITEM_PRODUCT_ID,
        "product_revision": RESOURCE_ITEM_PRODUCT_REVISION,
        "production_handler": RESOURCE_ITEM_HANDLER_ID,
        "profile": RESOURCE_ITEM_PROFILE_ID,
        "mode": RESOURCE_ITEM_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    RUINS_FLOW_ID: {
        "flow_id": RUINS_FLOW_ID,
        "product_id": RUINS_PRODUCT_ID,
        "product_revision": RUINS_PRODUCT_REVISION,
        "production_handler": RUINS_HANDLER_ID,
        "profile": RUINS_PROFILE_ID,
        "mode": RUINS_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    ALLIANCE_HELP_FLOW_ID: {
        "flow_id": ALLIANCE_HELP_FLOW_ID,
        "product_id": ALLIANCE_HELP_PRODUCT_ID,
        "product_revision": ALLIANCE_HELP_PRODUCT_REVISION,
        "production_handler": ALLIANCE_HELP_HANDLER_ID,
        "profile": ALLIANCE_HELP_PROFILE_ID,
        "mode": ALLIANCE_HELP_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    ALLIANCE_DONATION_FLOW_ID: {
        "flow_id": ALLIANCE_DONATION_FLOW_ID,
        "product_id": ALLIANCE_DONATION_PRODUCT_ID,
        "product_revision": ALLIANCE_DONATION_PRODUCT_REVISION,
        "production_handler": ALLIANCE_DONATION_HANDLER_ID,
        "profile": ALLIANCE_DONATION_PROFILE_ID,
        "mode": ALLIANCE_DONATION_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    ALLIANCE_SHOP_FLOW_ID: {
        "flow_id": ALLIANCE_SHOP_FLOW_ID,
        "product_id": ALLIANCE_SHOP_PRODUCT_ID,
        "product_revision": ALLIANCE_SHOP_PRODUCT_REVISION,
        "production_handler": ALLIANCE_SHOP_HANDLER_ID,
        "profile": ALLIANCE_SHOP_PROFILE_ID,
        "mode": ALLIANCE_SHOP_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    DAILY_SHOPS_FLOW_ID: {
        "flow_id": DAILY_SHOPS_FLOW_ID,
        "product_id": DAILY_SHOPS_PRODUCT_ID,
        "product_revision": DAILY_SHOPS_PRODUCT_REVISION,
        "production_handler": DAILY_SHOPS_HANDLER_ID,
        "profile": DAILY_SHOPS_PROFILE_ID,
        "mode": DAILY_SHOPS_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    NANO_MATERIAL_PRODUCTION_FLOW_ID: {
        "flow_id": NANO_MATERIAL_PRODUCTION_FLOW_ID,
        "product_id": NANO_MATERIAL_PRODUCTION_PRODUCT_ID,
        "product_revision": NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION,
        "production_handler": NANO_MATERIAL_PRODUCTION_HANDLER_ID,
        "profile": NANO_MATERIAL_PRODUCTION_PROFILE_ID,
        "mode": NANO_MATERIAL_PRODUCTION_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    NANOWEAPON_FLOW_ID: {
        "flow_id": NANOWEAPON_FLOW_ID,
        "product_id": NANOWEAPON_PRODUCT_ID,
        "product_revision": NANOWEAPON_PRODUCT_REVISION,
        "production_handler": NANOWEAPON_HANDLER_ID,
        "profile": NANOWEAPON_PROFILE_ID,
        "mode": NANOWEAPON_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    HERO_DUEL_FLOW_ID: {
        "flow_id": HERO_DUEL_FLOW_ID,
        "product_id": HERO_DUEL_PRODUCT_ID,
        "product_revision": HERO_DUEL_PRODUCT_REVISION,
        "production_handler": HERO_DUEL_HANDLER_ID,
        "profile": HERO_DUEL_PROFILE_ID,
        "mode": HERO_DUEL_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    RECOMMENDED_RESEARCH_FLOW_ID: {
        "flow_id": RECOMMENDED_RESEARCH_FLOW_ID,
        "product_id": RECOMMENDED_RESEARCH_PRODUCT_ID,
        "product_revision": RECOMMENDED_RESEARCH_PRODUCT_REVISION,
        "production_handler": RECOMMENDED_RESEARCH_HANDLER_ID,
        "profile": RECOMMENDED_RESEARCH_PROFILE_ID,
        "mode": RECOMMENDED_RESEARCH_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    FOOD_FARM_BOOST_FLOW_ID: {
        "flow_id": FOOD_FARM_BOOST_FLOW_ID,
        "product_id": FOOD_FARM_BOOST_PRODUCT_ID,
        "product_revision": FOOD_FARM_BOOST_PRODUCT_REVISION,
        "production_handler": FOOD_FARM_BOOST_HANDLER_ID,
        "profile": FOOD_FARM_BOOST_PROFILE_ID,
        "mode": FOOD_FARM_BOOST_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    HALL_OF_WAR_FLOW_ID: {
        "flow_id": HALL_OF_WAR_FLOW_ID,
        "product_id": HALL_OF_WAR_PRODUCT_ID,
        "product_revision": HALL_OF_WAR_PRODUCT_REVISION,
        "production_handler": HALL_OF_WAR_HANDLER_ID,
        "profile": HALL_OF_WAR_PROFILE_ID,
        "mode": HALL_OF_WAR_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    TROOP_TRAINING_FLOW_ID: {
        "flow_id": TROOP_TRAINING_FLOW_ID,
        "product_id": TROOP_TRAINING_PRODUCT_ID,
        "product_revision": TROOP_TRAINING_PRODUCT_REVISION,
        "production_handler": TROOP_TRAINING_HANDLER_ID,
        "profile": TROOP_TRAINING_PROFILE_ID,
        "mode": TROOP_TRAINING_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
    WALI_UPGRADE_FLOW_ID: {
        "flow_id": WALI_UPGRADE_FLOW_ID,
        "product_id": WALI_UPGRADE_PRODUCT_ID,
        "product_revision": WALI_UPGRADE_PRODUCT_REVISION,
        "production_handler": WALI_UPGRADE_HANDLER_ID,
        "profile": WALI_UPGRADE_PROFILE_ID,
        "mode": WALI_UPGRADE_PHASE_MODE,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
    },
}

# Entry fields are deliberately closed.  Runtime, queue, target, and scheduler
# implementation details do not belong in the production registration file.
ENTRY_FIELDS = frozenset(
    {
        "production_handler",
        "profile",
        "supported_profiles",
        "mode",
        "registration_status",
        "scheduler_eligible",
        "product_id",
        "product_revision",
    }
)


@dataclass(frozen=True)
class DisabledProductionEntry:
    flow_id: str
    production_handler: str | None
    profile: str | None
    supported_profiles: tuple[str, ...]
    mode: str
    registration_status: str
    scheduler_eligible: bool
    product_id: str | None = None
    product_revision: str | None = None

    @property
    def handler_id(self) -> str | None:
        """Stable spelling used by dispatch/evidence callers."""

        return self.production_handler

    @property
    def registered(self) -> bool:
        return self.registration_status == "REGISTERED"


@dataclass(frozen=True)
class RegisteredDispatchSnapshot:
    """Immutable dispatch-time copy of one accepted fixed registration."""

    flow_id: str
    product_id: str
    product_revision: str
    production_handler: str
    profile: str
    mode: str
    registration_status: str
    scheduler_eligible: bool

    def __post_init__(self) -> None:
        expected = _FIXED_BINDINGS.get(self.flow_id)
        actual = self.to_mapping()
        if (
            expected is None
            or actual != expected
            or type(self.scheduler_eligible) is not bool
        ):
            raise ValueError(
                "dispatch registration snapshot is not a fixed phase binding"
            )

    @classmethod
    def from_entry(cls, entry: DisabledProductionEntry) -> "RegisteredDispatchSnapshot":
        if not _entry_is_registered(entry):
            raise ValueError("only an exact registered phase entry can be dispatched")
        return cls(
            flow_id=entry.flow_id,
            product_id=entry.product_id or "",
            product_revision=entry.product_revision or "",
            production_handler=entry.production_handler or "",
            profile=entry.profile or "",
            mode=entry.mode,
            registration_status=entry.registration_status,
            scheduler_eligible=entry.scheduler_eligible,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RegisteredDispatchSnapshot":
        """Rehydrate and strictly validate retained dispatch evidence."""

        fields = {
            "flow_id",
            "product_id",
            "product_revision",
            "production_handler",
            "profile",
            "mode",
            "registration_status",
            "scheduler_eligible",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("dispatch registration snapshot is incomplete")
        return cls(
            flow_id=value["flow_id"],
            product_id=value["product_id"],
            product_revision=value["product_revision"],
            production_handler=value["production_handler"],
            profile=value["profile"],
            mode=value["mode"],
            registration_status=value["registration_status"],
            scheduler_eligible=value["scheduler_eligible"],
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "product_id": self.product_id,
            "product_revision": self.product_revision,
            "production_handler": self.production_handler,
            "profile": self.profile,
            "mode": self.mode,
            "registration_status": self.registration_status,
            "scheduler_eligible": self.scheduler_eligible,
        }

    @property
    def handler_id(self) -> str:
        return self.production_handler


@dataclass(frozen=True)
class CanonicalFlowRegistration:
    """Static, typed composition facts for a canonical service flow.

    This registry is code-owned and intentionally independent of the legacy
    disabled-production JSON and the BlueStacks runner registry.  It describes
    which offline handler is available; mutable enablement remains exclusively
    in ``BotStateManager``.
    """

    spec: FlowSpec
    descriptor: FlowDescriptor
    registration: RegisteredDispatchSnapshot
    handler_id: str
    cli_name: str | None = None
    """``--flow`` spelling accepted by ``automation-service serve``; ``None`` = not servable."""
    max_inputs: int | None = None
    """Total input budget of one run; the only owner. ``None`` = the route never executes."""

    @property
    def flow_id(self) -> str:
        return self.spec.flow_id

    @property
    def registered(self) -> bool:
        return self.descriptor.registration_status == "REGISTERED"

    @property
    def registration_status(self) -> str:
        return self.descriptor.registration_status

    @property
    def scheduler_eligible(self) -> bool:
        return self.descriptor.scheduler_eligible

    @property
    def product_id(self) -> str:
        return self.registration.product_id

    @property
    def product_revision(self) -> str:
        return self.registration.product_revision

    @property
    def production_handler(self) -> str:
        return self.handler_id

    @property
    def profile(self) -> str:
        return self.registration.profile

    @property
    def mode(self) -> str:
        return self.registration.mode

    @property
    def supported_profiles(self) -> tuple[str, ...]:
        return (self.profile,)

    def build_handler(self) -> Any:
        """Instantiate the fixed handler without importing handlers at module load."""

        if self.flow_id in {
            BIOENHANCER_FLOW_ID,
            SUPPLY_FLOW_ID,
            ULTIMATE_FLOW_ID,
            ENHANCEMENT_FLOW_ID,
            PERSONAL_MIGHT_FLOW_ID,
            DAILY_REWARDS_FLOW_ID,
            RESOURCE_ITEM_FLOW_ID,
            RUINS_FLOW_ID,
            ALLIANCE_HELP_FLOW_ID,
            ALLIANCE_DONATION_FLOW_ID,
            ALLIANCE_SHOP_FLOW_ID,
            DAILY_SHOPS_FLOW_ID,
            NANO_MATERIAL_PRODUCTION_FLOW_ID,
            NANOWEAPON_FLOW_ID,
            HERO_DUEL_FLOW_ID,
            RECOMMENDED_RESEARCH_FLOW_ID,
            FOOD_FARM_BOOST_FLOW_ID,
            HALL_OF_WAR_FLOW_ID,
            TROOP_TRAINING_FLOW_ID,
            WALI_UPGRADE_FLOW_ID,
        }:
            # Only explicit supervised serve installs its executor and held-owner
            # checkpoint. Generic composition must never create native authority.
            from .handlers import DisabledHandler
            return DisabledHandler(self.descriptor)

        from .handlers import (
            CampaignApSelectionHandler,
            NovaPraiseSelectionHandler,
            RecruitmentMaintenanceSelectionHandler,
            WorldNavigationSelectionHandler,
        )

        handler_types = {
            CAMPAIGN_FLOW_ID: CampaignApSelectionHandler,
            NOVA_FLOW_ID: NovaPraiseSelectionHandler,
            RECRUITMENT_FLOW_ID: RecruitmentMaintenanceSelectionHandler,
            WORLD_FLOW_ID: WorldNavigationSelectionHandler,
        }
        handler_type = handler_types.get(self.flow_id)
        if handler_type is None:
            raise ValueError(f"no canonical handler for flow: {self.flow_id}")
        return handler_type(self.registration)


def _canonical_registration(
    flow_id: str,
    *,
    family: str,
    variant: str,
    cadence: str,
    reset_scoped: bool = True,
    recurrence: RecurrenceProjection | None = None,
    observation_only_completion: bool = False,
    cli_name: str | None = None,
    max_inputs: int | None = None,
) -> CanonicalFlowRegistration:
    binding = _FIXED_BINDINGS[flow_id]
    snapshot = RegisteredDispatchSnapshot(
        flow_id=flow_id,
        product_id=binding["product_id"],
        product_revision=binding["product_revision"],
        production_handler=binding["production_handler"],
        profile=binding["profile"],
        mode=binding["mode"],
        registration_status="REGISTERED",
        scheduler_eligible=True,
    )
    descriptor = FlowDescriptor(
        flow_id=flow_id,
        owner="automation_service",
        family=family,
        variant=variant,
        cadence=cadence,
        priority=1,
        reset_scoped=reset_scoped,
        scheduler_eligible=True,
        accepted_product=binding["product_id"],
        product_revision=binding["product_revision"],
        registration_status="REGISTERED",
        recurrence=recurrence,
    )
    return CanonicalFlowRegistration(
        spec=FlowSpec(
            flow_id=flow_id,
            default_enabled=False,
            priority=descriptor.priority,
            cadence=cadence,
            observation_only_completion=observation_only_completion,
        ),
        descriptor=descriptor,
        registration=snapshot,
        handler_id=binding["production_handler"],
        cli_name=cli_name,
        max_inputs=max_inputs,
    )


# The tuple is immutable and deterministic.  Do not derive it from a file,
# environment, queue, or runner registration.
CANONICAL_FLOW_REGISTRY: tuple[CanonicalFlowRegistration, ...] = (
    _canonical_registration(
        WORLD_FLOW_ID,
        family="world_map_navigation",
        variant="navigation_only",
        cadence="daily_once_per_reset",
    ),
    _canonical_registration(
        NOVA_FLOW_ID,
        max_inputs=NOVA_MAX_INPUTS,
        cli_name="nova",
        family="nova_praise",
        variant="supervised_one_free_pulse",
        cadence="cooldown_pulse",
        reset_scoped=False,
    ),
    _canonical_registration(
        RECRUITMENT_FLOW_ID,
        max_inputs=RECRUITMENT_MAX_INPUTS,
        cli_name="recruitment",
        family="recruitment",
        variant="free_attempt_maintenance",
        cadence="cooldown_pulse",
        reset_scoped=False,
    ),
    _canonical_registration(
        CAMPAIGN_FLOW_ID,
        max_inputs=CAMPAIGN_ROUTE_MAX_INPUTS,
        cli_name="campaign",
        family="campaign_ap",
        variant="drain_available_ap",
        cadence="after_ap_drain",
        reset_scoped=False,
        recurrence=RecurrenceProjection(
            RecurrenceClass.AP_REGENERATION,
            observed_at_utc=0.0,
            observed_balance=0.0,
        ),
    ),
    _canonical_registration(
        BIOENHANCER_FLOW_ID,
        max_inputs=BIOENHANCER_MAX_INPUTS,
        cli_name="bioenhancer",
        family="bioenhancer_research",
        variant="one_free_pulse",
        cadence="cooldown_pulse",
        reset_scoped=False,
    ),
    _canonical_registration(
        SUPPLY_FLOW_ID,
        max_inputs=SUPPLY_MAX_INPUTS,
        cli_name="supply",
        family="supply_depot",
        variant="free_until_exhausted",
        cadence="daily_once_per_reset",
        observation_only_completion=True,
    ),
    _canonical_registration(
        ULTIMATE_FLOW_ID,
        max_inputs=ULTIMATE_MAX_INPUTS,
        cli_name="ultimate",
        family="ultimate_challenge_daily",
        variant="one_daily_flee",
        cadence="daily_once_per_reset",
        observation_only_completion=True,
    ),
    _canonical_registration(
        ENHANCEMENT_FLOW_ID,
        max_inputs=ENHANCEMENT_MAX_INPUTS,
        cli_name="enhancement",
        family="enhancement_family",
        variant="gear_chip_module",
        cadence="daily_once_per_reset",
        observation_only_completion=True,
    ),
    _canonical_registration(
        PERSONAL_MIGHT_FLOW_ID,
        max_inputs=PERSONAL_MIGHT_MAX_INPUTS,
        cli_name="personal-might",
        family="personal_might_praise",
        variant="one_daily_praise",
        cadence="daily_once_per_reset",
        observation_only_completion=True,
    ),
    _canonical_registration(
        DAILY_REWARDS_FLOW_ID,
        max_inputs=DAILY_REWARDS_MAX_INPUTS,
        cli_name="daily-rewards",
        family="daily_rewards",
        variant="aggregate_then_ready_chests",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        RESOURCE_ITEM_FLOW_ID,
        max_inputs=RESOURCE_ITEM_MAX_INPUTS,
        cli_name="resource-item",
        family="resource_item",
        variant="one_owned_1k_food",
        cadence="daily_once_per_reset",
        observation_only_completion=True,
    ),
    _canonical_registration(
        RUINS_FLOW_ID,
        max_inputs=RUINS_MAX_INPUTS,
        cli_name="ruins",
        family="ruins_challenge",
        variant="challenge_then_green_chests",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        ALLIANCE_HELP_FLOW_ID,
        max_inputs=ALLIANCE_HELP_MAX_INPUTS,
        cli_name="alliance-help",
        family="alliance_help",
        variant="ten_successful_free_requests",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        ALLIANCE_DONATION_FLOW_ID,
        max_inputs=ALLIANCE_DONATION_MAX_INPUTS,
        cli_name="alliance-donation",
        family="alliance_donation",
        variant="ten_hot_donations",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        ALLIANCE_SHOP_FLOW_ID,
        max_inputs=ALLIANCE_SHOP_MAX_INPUTS,
        cli_name="alliance-shop",
        family="alliance_shop",
        variant="one_weekly_or_other",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        DAILY_SHOPS_FLOW_ID,
        max_inputs=DAILY_SHOPS_MAX_INPUTS,
        cli_name="daily-shops",
        family="daily_shops",
        variant="ruins_and_rare_earth_max",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        NANO_MATERIAL_PRODUCTION_FLOW_ID,
        max_inputs=NANO_MATERIAL_PRODUCTION_MAX_INPUTS,
        cli_name="nano-material-production",
        family="nano_material_production",
        variant="six_hour_single_slot",
        cadence="timer",
        reset_scoped=False,
    ),
    _canonical_registration(
        NANOWEAPON_FLOW_ID,
        max_inputs=NANOWEAPON_MAX_INPUTS,
        cli_name="nanoweapon",
        family="nanoweapon",
        variant="normal_craft_100_nano_parts",
        cadence="cooldown_pulse",
    ),

    _canonical_registration(
        HERO_DUEL_FLOW_ID,
        max_inputs=HERO_DUEL_MAX_INPUTS,
        cli_name="hero-duel",
        family="hero_duel",
        variant="up_to_three_free_entry_flee_cycles",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        RECOMMENDED_RESEARCH_FLOW_ID,
        max_inputs=RECOMMENDED_RESEARCH_MAX_INPUTS,
        cli_name="recommended-research",
        family="recommended_research",
        variant="first_displayed_recommendation_idle_affordable_start",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        FOOD_FARM_BOOST_FLOW_ID,
        max_inputs=FOOD_FARM_BOOST_MAX_INPUTS,
        cli_name="food-farm-boost",
        family="food_farm_boost",
        variant="one_daily_food_farm_boost",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        HALL_OF_WAR_FLOW_ID,
        max_inputs=HALL_OF_WAR_MAX_INPUTS,
        cli_name="hall-of-war",
        family="hall_of_war",
        variant="zombie_zero_attack_and_daily_reward",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
    _canonical_registration(
        TROOP_TRAINING_FLOW_ID,
        max_inputs=TROOP_TRAINING_MAX_INPUTS,
        cli_name="troop-training",
        family="troop_training",
        variant="four_fixed_training_variants",
        cadence="timer",
        observation_only_completion=True,
    ),
    _canonical_registration(
        WALI_UPGRADE_FLOW_ID,
        max_inputs=WALI_UPGRADE_MAX_INPUTS,
        cli_name="wali-upgrade",
        family="wali_upgrade",
        variant="three_single_level_upgrades_with_standard_evolution",
        cadence="cooldown_pulse",
        observation_only_completion=True,
    ),
)


def load_canonical_registry() -> tuple[CanonicalFlowRegistration, ...]:
    """Return static canonical flow composition facts.

    A function keeps call sites symmetrical with the retired registry loader,
    while returning the immutable code-owned tuple rather than reading disk.
    """

    return CANONICAL_FLOW_REGISTRY


canonical_registry = load_canonical_registry


def canonical_flow_specs() -> tuple[FlowSpec, ...]:
    """Return disabled-by-default static specs for SQLite initialization."""

    return tuple(entry.spec for entry in CANONICAL_FLOW_REGISTRY)


def canonical_descriptors() -> tuple[FlowDescriptor, ...]:
    """Return canonical descriptors without consulting any external registry."""

    return tuple(entry.descriptor for entry in CANONICAL_FLOW_REGISTRY)


def canonical_entry(flow_id: str) -> CanonicalFlowRegistration:
    """Return the one canonical registration for ``flow_id``.

    Handlers and adapters derive their descriptors from this entry instead of
    re-spelling family, variant, cadence, and product facts.
    """

    entry = next(
        (item for item in CANONICAL_FLOW_REGISTRY if item.flow_id == flow_id),
        None,
    )
    if entry is None:
        raise ValueError(f"unknown canonical flow: {flow_id}")
    return entry


def servable_flow_names() -> dict[str, str]:
    """Map each ``automation-service serve --flow`` name to its flow id."""

    return {
        item.cli_name: item.flow_id
        for item in CANONICAL_FLOW_REGISTRY
        if item.cli_name is not None
    }


def build_canonical_handler(flow_id: str) -> Any:
    """Build one fixed canonical handler by flow identity."""

    return canonical_entry(flow_id).build_handler()


_REGISTRY_LOCK = threading.RLock()


def _entry_is_registered(entry: DisabledProductionEntry) -> bool:
    expected = _FIXED_BINDINGS.get(entry.flow_id)
    return bool(
        expected is not None
        and entry.production_handler == expected["production_handler"]
        and entry.profile == expected["profile"]
        and entry.supported_profiles == (expected["profile"],)
        and entry.product_id == expected["product_id"]
        and entry.product_revision == expected["product_revision"]
        and entry.mode == expected["mode"]
        and entry.registration_status == expected["registration_status"]
        and entry.scheduler_eligible is expected["scheduler_eligible"]
    )


def _entry_is_world_registered(entry: DisabledProductionEntry) -> bool:
    return entry.flow_id == WORLD_FLOW_ID and _entry_is_registered(entry)


def _entry_is_nova_registered(entry: DisabledProductionEntry) -> bool:
    return entry.flow_id == NOVA_FLOW_ID and _entry_is_registered(entry)


def _entry_is_disabled(entry: DisabledProductionEntry) -> bool:
    return bool(
        entry.production_handler is None
        and entry.profile is None
        and entry.supported_profiles == ()
        and entry.product_id is None
        and entry.product_revision is None
        and entry.mode == "disabled"
        and entry.registration_status == "NOT_REGISTERED"
        and entry.scheduler_eligible is False
    )


def _validate_string_or_none(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(
            f"{field} must be unavailable or a normalized non-empty string"
        )
    return value


def _parse_entries(payload: Mapping[str, Any]) -> tuple[DisabledProductionEntry, ...]:
    if (
        payload.get("schema_version") != 1
        or payload.get("registry_kind") != "disabled_production_handlers"
    ):
        raise ValueError("unsupported disabled production registry")
    flows = payload.get("flows")
    if not isinstance(flows, Mapping) or not flows:
        raise ValueError("disabled production registry requires flows")

    entries: list[DisabledProductionEntry] = []
    for flow_id, value in flows.items():
        if (
            not isinstance(flow_id, str)
            or not flow_id.strip()
            or flow_id != flow_id.strip()
            or not isinstance(value, Mapping)
        ):
            raise ValueError("invalid disabled production registry entry")
        if set(value) != ENTRY_FIELDS:
            raise ValueError(
                "registry entry owns only fixed product/handler/profile registration fields"
            )
        supported = value["supported_profiles"]
        if type(supported) is not list or any(
            not isinstance(profile, str)
            or not profile.strip()
            or profile != profile.strip()
            for profile in supported
        ):
            raise ValueError(
                "supported_profiles must be a list of normalized non-empty strings"
            )
        eligible = value["scheduler_eligible"]
        if type(eligible) is not bool:
            raise ValueError("scheduler_eligible must be a boolean")
        mode = value["mode"]
        status = value["registration_status"]
        if not isinstance(mode, str) or not mode.strip() or mode != mode.strip():
            raise ValueError("registry mode must be a normalized string")
        if not isinstance(status, str) or status not in {
            "REGISTERED",
            "NOT_REGISTERED",
        }:
            raise ValueError("unsupported registry registration status")
        entry = DisabledProductionEntry(
            flow_id=flow_id,
            production_handler=_validate_string_or_none(
                value["production_handler"], "production_handler"
            ),
            profile=_validate_string_or_none(value["profile"], "profile"),
            supported_profiles=tuple(supported),
            mode=mode,
            registration_status=status,
            scheduler_eligible=eligible,
            product_id=_validate_string_or_none(value["product_id"], "product_id"),
            product_revision=_validate_string_or_none(
                value["product_revision"], "product_revision"
            ),
        )
        if entry.registration_status == "REGISTERED":
            if not _entry_is_registered(entry):
                raise ValueError(
                    "only an exact fixed phase-canary registration is allowed"
                )
        elif not _entry_is_disabled(entry):
            raise ValueError("all non-registered entries must remain fully disabled")
        entries.append(entry)

    registered = [entry for entry in entries if entry.registered]
    if len(registered) > 1:
        raise ValueError("production registry permits at most one registered flow")
    if registered and not _entry_is_registered(registered[0]):
        raise ValueError("registered production entry is not a fixed phase binding")
    return tuple(sorted(entries, key=lambda item: item.flow_id))


def _load_payload(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("cannot load disabled production registry") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("disabled production registry must be an object")
    return payload


def load_disabled_registry(
    path: Path | None = None,
) -> tuple[DisabledProductionEntry, ...]:
    """Load and strictly validate the checked-in registration authority."""

    registry_path = Path(REGISTRY_PATH if path is None else path)
    with _REGISTRY_LOCK:
        return _parse_entries(_load_payload(registry_path))


load_production_registry = load_disabled_registry


@contextmanager
def _registry_file_lock(path: Path) -> Iterator[None]:
    """Serialize cross-process read/replace operations without a second authority."""

    lock_path = Path(str(path) + ".lock")
    descriptor: int | None = None
    started = time.monotonic()
    while descriptor is None:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # A stale lock can only be reclaimed after a bounded wait; normal
            # concurrent callers wait for the holder and then retry.
            if time.monotonic() - started > 10.0:
                try:
                    if time.time() - lock_path.stat().st_mtime > 10.0:
                        lock_path.unlink()
                        continue
                except OSError:
                    pass
            time.sleep(0.005)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _write_payload_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)



def consume_registered_entry(
    flow_id: str = WORLD_FLOW_ID,
    *,
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Legacy-only atomic snapshot consumption for unmigrated routes."""

    registry_path = Path(REGISTRY_PATH if path is None else path)
    if flow_id not in _FIXED_BINDINGS:
        return None
    with _REGISTRY_LOCK, _registry_file_lock(registry_path):
        payload = dict(_load_payload(registry_path))
        entries = _parse_entries(payload)
        entry = next((item for item in entries if item.flow_id == flow_id), None)
        if entry is None or not _entry_is_registered(entry):
            return None
        snapshot = RegisteredDispatchSnapshot.from_entry(entry)
        flows = dict(payload["flows"])
        flows[flow_id] = {
            "production_handler": None,
            "profile": None,
            "supported_profiles": [],
            "mode": "disabled",
            "registration_status": "NOT_REGISTERED",
            "scheduler_eligible": False,
            "product_id": None,
            "product_revision": None,
        }
        payload["flows"] = flows
        # Validate the post-consumption state before replacing the authority.
        _parse_entries(payload)
        _write_payload_atomic(registry_path, payload)
        return snapshot


consume_world_registration = consume_registered_entry


def consume_nova_registration(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Atomically consume the exact registered Nova entry."""

    return consume_registered_entry(NOVA_FLOW_ID, path=path)


def consume_recruitment_registration(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Atomically consume the exact registered Recruitment maintenance entry."""

    return consume_registered_entry(RECRUITMENT_FLOW_ID, path=path)

def consume_campaign_registration(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Atomically consume the exact registered Campaign AP entry."""

    return consume_registered_entry(CAMPAIGN_FLOW_ID, path=path)


def world_registration_snapshot(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Return the exact registered World snapshot without consuming it."""

    entry = next(
        (
            item
            for item in load_disabled_registry(path)
            if item.flow_id == WORLD_FLOW_ID
        ),
        None,
    )
    return (
        RegisteredDispatchSnapshot.from_entry(entry)
        if entry is not None and entry.registered
        else None
    )


def nova_registration_snapshot(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Return the exact registered Nova snapshot without consuming it."""

    entry = next(
        (item for item in load_disabled_registry(path) if item.flow_id == NOVA_FLOW_ID),
        None,
    )
    return (
        RegisteredDispatchSnapshot.from_entry(entry)
        if entry is not None and entry.registered
        else None
    )


def recruitment_registration_snapshot(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Return the registered Recruitment snapshot without consuming it."""

    entry = next(
        (
            item
            for item in load_disabled_registry(path)
            if item.flow_id == RECRUITMENT_FLOW_ID
        ),
        None,
    )
    return (
        RegisteredDispatchSnapshot.from_entry(entry)
        if entry is not None and entry.registered
        else None
    )

def campaign_registration_snapshot(
    path: Path | None = None,
) -> RegisteredDispatchSnapshot | None:
    """Return the registered Campaign AP snapshot without consuming it."""

    entry = next(
        (
            item
            for item in load_disabled_registry(path)
            if item.flow_id == CAMPAIGN_FLOW_ID
        ),
        None,
    )
    return (
        RegisteredDispatchSnapshot.from_entry(entry)
        if entry is not None and entry.registered
        else None
    )


__all__ = [
    "CanonicalFlowRegistration",
    "CANONICAL_FLOW_REGISTRY",
    "canonical_descriptors",
    "canonical_entry",
    "canonical_flow_specs",
    "canonical_registry",
    "build_canonical_handler",
    "load_canonical_registry",
    "servable_flow_names",
    "DisabledProductionEntry",
    "ENTRY_FIELDS",
    "REGISTRY_PATH",
    "RegisteredDispatchSnapshot",
    "WORLD_FLOW_ID",
    "WORLD_PRODUCT_ID",
    "WORLD_PRODUCT_REVISION",
    "WORLD_HANDLER_ID",
    "WORLD_SELECTION_HANDLER_ID",
    "WORLD_PROFILE_ID",
    "WORLD_PROFILE",
    "WORLD_PRODUCT",
    "WORLD_REVISION",
    "WORLD_PHASE_MODE",
    "NOVA_FLOW_ID",
    "NOVA_PRODUCT_ID",
    "NOVA_PRODUCT_REVISION",
    "NOVA_HANDLER_ID",
    "NOVA_SELECTION_HANDLER_ID",
    "NOVA_PROFILE_ID",
    "NOVA_PROFILE",
    "NOVA_PRODUCT",
    "NOVA_REVISION",
    "NOVA_PHASE_MODE",
    "NOVA_MAX_INPUTS",
    "RECRUITMENT_FLOW_ID",
    "RECRUITMENT_PRODUCT_ID",
    "RECRUITMENT_PRODUCT_REVISION",
    "RECRUITMENT_HANDLER_ID",
    "RECRUITMENT_SELECTION_HANDLER_ID",
    "RECRUITMENT_PROFILE_ID",
    "RECRUITMENT_PROFILE",
    "RECRUITMENT_PRODUCT",
    "RECRUITMENT_REVISION",
    "RECRUITMENT_PHASE_MODE",
    "RECRUITMENT_MAX_INPUTS",
    "CAMPAIGN_FLOW_ID",
    "CAMPAIGN_PRODUCT_ID",
    "CAMPAIGN_PRODUCT_REVISION",
    "CAMPAIGN_HANDLER_ID",
    "CAMPAIGN_SELECTION_HANDLER_ID",
    "CAMPAIGN_PROFILE_ID",
    "CAMPAIGN_PROFILE",
    "CAMPAIGN_PRODUCT",
    "CAMPAIGN_REVISION",
    "CAMPAIGN_PHASE_MODE",
    "CAMPAIGN_ROUTE_MAX_INPUTS",
    "SUPPLY_FLOW_ID",
    "SUPPLY_PRODUCT_ID",
    "SUPPLY_PRODUCT_REVISION",
    "SUPPLY_HANDLER_ID",
    "SUPPLY_PROFILE_ID",
    "SUPPLY_PHASE_MODE",
    "SUPPLY_MAX_INPUTS",
    "ULTIMATE_FLOW_ID",
    "ULTIMATE_PRODUCT_ID",
    "ULTIMATE_PRODUCT_REVISION",
    "ULTIMATE_HANDLER_ID",
    "ULTIMATE_PROFILE_ID",
    "ULTIMATE_PHASE_MODE",
    "ULTIMATE_MAX_INPUTS",
    "ENHANCEMENT_FLOW_ID",
    "ENHANCEMENT_PRODUCT_ID",
    "ENHANCEMENT_PRODUCT_REVISION",
    "ENHANCEMENT_HANDLER_ID",
    "ENHANCEMENT_PROFILE_ID",
    "ENHANCEMENT_PHASE_MODE",
    "ENHANCEMENT_MAX_INPUTS",
    "PERSONAL_MIGHT_FLOW_ID",
    "PERSONAL_MIGHT_PRODUCT_ID",
    "PERSONAL_MIGHT_PRODUCT_REVISION",
    "PERSONAL_MIGHT_HANDLER_ID",
    "PERSONAL_MIGHT_PROFILE_ID",
    "PERSONAL_MIGHT_PHASE_MODE",
    "PERSONAL_MIGHT_MAX_INPUTS",
    "DAILY_REWARDS_FLOW_ID",
    "DAILY_REWARDS_PRODUCT_ID",
    "DAILY_REWARDS_PRODUCT_REVISION",
    "DAILY_REWARDS_HANDLER_ID",
    "DAILY_REWARDS_PROFILE_ID",
    "DAILY_REWARDS_PHASE_MODE",
    "DAILY_REWARDS_MAX_INPUTS",
    "RESOURCE_ITEM_FLOW_ID",
    "RESOURCE_ITEM_PRODUCT_ID",
    "RESOURCE_ITEM_PRODUCT_REVISION",
    "RESOURCE_ITEM_HANDLER_ID",
    "RESOURCE_ITEM_PROFILE_ID",
    "RESOURCE_ITEM_PHASE_MODE",
    "RESOURCE_ITEM_MAX_INPUTS",
    "RUINS_FLOW_ID",
    "RUINS_PRODUCT_ID",
    "RUINS_PRODUCT_REVISION",
    "RUINS_HANDLER_ID",
    "RUINS_PROFILE_ID",
    "RUINS_PHASE_MODE",
    "RUINS_MAX_INPUTS",
    "ALLIANCE_HELP_FLOW_ID",
    "ALLIANCE_HELP_PRODUCT_ID",
    "ALLIANCE_HELP_PRODUCT_REVISION",
    "ALLIANCE_HELP_HANDLER_ID",
    "ALLIANCE_HELP_PROFILE_ID",
    "ALLIANCE_HELP_PHASE_MODE",
    "ALLIANCE_HELP_MAX_INPUTS",
    "ALLIANCE_DONATION_FLOW_ID",
    "ALLIANCE_DONATION_PRODUCT_ID",
    "ALLIANCE_DONATION_PRODUCT_REVISION",
    "ALLIANCE_DONATION_HANDLER_ID",
    "ALLIANCE_DONATION_PROFILE_ID",
    "ALLIANCE_DONATION_PHASE_MODE",
    "ALLIANCE_DONATION_MAX_INPUTS",
    "ALLIANCE_SHOP_FLOW_ID",
    "ALLIANCE_SHOP_PRODUCT_ID",
    "ALLIANCE_SHOP_PRODUCT_REVISION",
    "ALLIANCE_SHOP_HANDLER_ID",
    "ALLIANCE_SHOP_PROFILE_ID",
    "ALLIANCE_SHOP_PHASE_MODE",
    "ALLIANCE_SHOP_MAX_INPUTS",
    "DAILY_SHOPS_FLOW_ID",
    "DAILY_SHOPS_PRODUCT_ID",
    "DAILY_SHOPS_PRODUCT_REVISION",
    "DAILY_SHOPS_HANDLER_ID",
    "DAILY_SHOPS_PROFILE_ID",
    "DAILY_SHOPS_PHASE_MODE",
    "DAILY_SHOPS_MAX_INPUTS",
    "NANO_MATERIAL_PRODUCTION_FLOW_ID",
    "NANO_MATERIAL_PRODUCTION_PRODUCT_ID",
    "NANO_MATERIAL_PRODUCTION_PRODUCT_REVISION",
    "NANO_MATERIAL_PRODUCTION_HANDLER_ID",
    "NANO_MATERIAL_PRODUCTION_PROFILE_ID",
    "NANO_MATERIAL_PRODUCTION_PHASE_MODE",
    "NANO_MATERIAL_PRODUCTION_MAX_INPUTS",
    "NANOWEAPON_FLOW_ID",
    "NANOWEAPON_PRODUCT_ID",
    "NANOWEAPON_PRODUCT_REVISION",
    "NANOWEAPON_HANDLER_ID",
    "NANOWEAPON_PROFILE_ID",
    "NANOWEAPON_PHASE_MODE",
    "NANOWEAPON_MAX_INPUTS",
    'HERO_DUEL_FLOW_ID',
    'HERO_DUEL_PRODUCT_ID',
    'HERO_DUEL_PRODUCT_REVISION',
    'HERO_DUEL_HANDLER_ID',
    'HERO_DUEL_PROFILE_ID',
    'HERO_DUEL_PHASE_MODE',
    'HERO_DUEL_MAX_INPUTS',
    'RECOMMENDED_RESEARCH_FLOW_ID',
    'RECOMMENDED_RESEARCH_PRODUCT_ID',
    'RECOMMENDED_RESEARCH_PRODUCT_REVISION',
    'RECOMMENDED_RESEARCH_HANDLER_ID',
    'RECOMMENDED_RESEARCH_PROFILE_ID',
    'RECOMMENDED_RESEARCH_PHASE_MODE',
    'RECOMMENDED_RESEARCH_MAX_INPUTS',
    'FOOD_FARM_BOOST_FLOW_ID',
    'FOOD_FARM_BOOST_PRODUCT_ID',
    'FOOD_FARM_BOOST_PRODUCT_REVISION',
    'FOOD_FARM_BOOST_HANDLER_ID',
    'FOOD_FARM_BOOST_PROFILE_ID',
    'FOOD_FARM_BOOST_PHASE_MODE',
    'FOOD_FARM_BOOST_MAX_INPUTS',
    "WALI_UPGRADE_FLOW_ID",
    "WALI_UPGRADE_PRODUCT_ID",
    "WALI_UPGRADE_PRODUCT_REVISION",
    "WALI_UPGRADE_HANDLER_ID",
    "WALI_UPGRADE_PROFILE_ID",
    "WALI_UPGRADE_PHASE_MODE",
    "WALI_UPGRADE_MAX_INPUTS",
    "consume_registered_entry",
    "consume_world_registration",
    "consume_nova_registration",
    "consume_recruitment_registration",
    "consume_campaign_registration",
    "load_disabled_registry",
    "load_production_registry",
    "nova_registration_snapshot",
    "recruitment_registration_snapshot",
    "campaign_registration_snapshot",
    "world_registration_snapshot",
]
