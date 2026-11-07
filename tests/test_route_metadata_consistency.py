"""Route facts have one owner; every other copy is derived from it or checked here (issue #34).

Owners (see ``docs/adding-a-route.md`` for the full table and why the authorities stay separate):

* ``automation_service/registry.py`` ``CANONICAL_FLOW_REGISTRY``: flow id, family, variant, cadence,
  product id/revision, ``--flow`` name, total input budget (``max_inputs``) of every service route.
* ``tasks/flow_delivery_bluestacks_registry.json``: which routes have an operator runner.
* ``tasks/flow_delivery_disabled_production_registry.json``: legacy disabled-production policy.
* ``tasks/flow_delivery_queue.json``: development queue, one record per flow.
* ``tasks/gameplay_flow_contracts/*.json`` + ``tasks/flow_delivery_product_policy.json``: product contracts.

The authorities stay separate: each may hold facts the others must not (a flow can be in the queue and
contracts without being a service route). This module only asserts the *relations* between them.

The registry's product revision is deliberately NOT compared with the product-policy record revision:
they are different vocabularies (the scheduler compares the registry value with itself; the policy
record revision versions a policy record and is only checked against contract bindings below).
"""

from __future__ import annotations

import argparse
from importlib import import_module
import json
import os
from pathlib import Path
import re
import unittest

from automation_service import state as state_module
from automation_service.cli import build_parser
from automation_service.contracts import RecurrenceClass
from automation_service.registry import (
    ALLIANCE_DONATION_FLOW_ID, ALLIANCE_DONATION_PROFILE_ID, ALLIANCE_HELP_FLOW_ID,
    ALLIANCE_HELP_PROFILE_ID, ALLIANCE_SHOP_FLOW_ID, ALLIANCE_SHOP_PROFILE_ID,
    CAMPAIGN_FLOW_ID, CAMPAIGN_PRODUCT_REVISION, CANONICAL_FLOW_REGISTRY,
    DAILY_REWARDS_FLOW_ID, DAILY_SHOPS_FLOW_ID, DAILY_SHOPS_PROFILE_ID,
    FOOD_FARM_BOOST_FLOW_ID, FOOD_FARM_BOOST_PROFILE_ID, HERO_DUEL_FLOW_ID,
    HERO_DUEL_PROFILE_ID, NANO_MATERIAL_PRODUCTION_FLOW_ID,
    NANO_MATERIAL_PRODUCTION_PROFILE_ID, NANOWEAPON_FLOW_ID, NANOWEAPON_PROFILE_ID,
    RECOMMENDED_RESEARCH_FLOW_ID, RECOMMENDED_RESEARCH_PROFILE_ID,
    RESOURCE_ITEM_FLOW_ID, RUINS_FLOW_ID, RUINS_PROFILE_ID,
    load_disabled_registry, canonical_entry, servable_flow_names,
)
from automation_service.service import AutomationService, _runner_attribute
from safe_action_core import policy as safe_policy
from safe_action_core import store as store_module
from scripts import pnsctl
from tasks.gameplay_flow_contracts import list_flow_contract_ids, load_all_flow_contracts
from tasks.product_authority import (
    load_product_authority,
    validate_contract_product_authority_bindings,
)

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"
README = ROOT / "README.md"
AUTOMATION_DOC = ROOT / "docs" / "automation-service.md"
NAVIGATION_ONLY = "navigation_only"

OLD_CAMPAIGN_ID = "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY"

# --- explicit, reasoned exceptions -------------------------------------------------------------

NO_OPERATOR_RUNNER = {
    "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE": "operator runner retired in #35; canonical serve is the only runner",
    DAILY_REWARDS_FLOW_ID: "Daily Row Claim wrapper retired in Batch A; canonical serve uses its fixed native binding",
    RESOURCE_ITEM_FLOW_ID: "Daily Resource Item wrapper retired in Batch A; canonical serve uses its fixed native binding",
    RUINS_FLOW_ID: "Ruins operator wrapper retired in Batch B; canonical serve uses its fixed native binding",
    ALLIANCE_HELP_FLOW_ID: "Alliance Help is canonical-service-only and has no operator wrapper",
    ALLIANCE_DONATION_FLOW_ID: "Alliance Donation is canonical-service-only and has no operator wrapper",
    ALLIANCE_SHOP_FLOW_ID: "Alliance Shop is canonical-service-only and has no operator wrapper",
    DAILY_SHOPS_FLOW_ID: "Daily Shops is canonical-service-only and has no operator wrapper",
    NANO_MATERIAL_PRODUCTION_FLOW_ID: "Nano Material Production is canonical-service-only and has no operator wrapper",
    NANOWEAPON_FLOW_ID: "Nanoweapon is canonical-service-only and has no operator wrapper",
    HERO_DUEL_FLOW_ID: "Hero Duel is canonical-service-only and has no operator wrapper",
    RECOMMENDED_RESEARCH_FLOW_ID: "Recommended Research is canonical-service-only and has no operator wrapper",
    FOOD_FARM_BOOST_FLOW_ID: "Food Farm Boost is canonical-service-only and has no operator wrapper",
}

# Retained operator-registry flows with no development-session input default in ``pnsctl._DEFAULT_MAX_INPUTS``.
NO_DEFAULT_MAX_INPUTS = {
    "AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE": "own route cap in its flow_delivery module",
    "CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION": "own route cap in its flow_delivery module",
    "CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION": "survey budget is queue/contract owned (272 navigation inputs)",
    "WORLD-MAP-NAVIGATION-FOUNDATION": "MAX_ROUTE_INPUTS in world_map_navigation_bluestacks",
}

# Campaign's development-session ceiling (pnsctl) is a different fact from the service route budget:
# the service drains AP over many battles (CAMPAIGN_MAX_INPUTS), a development session is one battle.
DEFAULT_MAX_INPUTS_DIFFERS_FROM_REGISTRY = {
    CAMPAIGN_FLOW_ID: "development session ceiling (16) vs whole AP-drain service budget",
}

# Flow ids in the contracts directory that are historical and appear in no registry or queue.
CONTRACT_ONLY_FLOWS = {
    "PERSONAL-MIGHT-PRAISE-BLISS-PILOT": "retained Bliss pilot contract; superseded by the BlueStacks integration",
}

# Queue keys that name files the repository must still contain. Historical records
# (live_attempts, receipts, retirement_result.deleted_paths, artifact_root) are never checked here.
QUEUE_PATH_KEYS = (
    "implementation_entrypoints",
    "implementation_allowlist_seed",
    "focused_tests",
    "completion_tests",
    "reference_docs",
)

# Where the pre-#36 Campaign flow id may still appear, and why. Anything else is a missed rename.
OLD_CAMPAIGN_ID_FILES = {
    "automation_service/state.py": "RENAMED_FLOW_IDS migration constant",
    "safe_action_core/store.py": "RENAMED_TASK_IDS migration constant",
    "tasks/campaign_victory_recovery.py": "accepts retained old-prefix victory sessions",
    "tasks/flow_delivery_queue.json": "historical live_attempts and the retained artifact_root",
    "tasks/daily_quest_execution_matrix.json": "historical matrix record",
    "tasks/gameplay_flow_contracts/CAMPAIGN-AP-AUTO-BATTLE.json": "retained evidence references",
    "tasks/gameplay_flow_contracts/CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION.json": "retained evidence references",
    "docs/backlog/operations.md": "historical backlog record",
    "docs/backlog/resources.md": "historical backlog record",
    "docs/validation/bluestacks-20261031/summary.json": "retained validation summary",
    "docs/validation/campaign-ap-auto-battle-live-canary-manifest.json": "retained validation manifest",
    "tests/test_campaign_atlas_chapter_nav.py": "retained evidence path",
    "tests/test_flow_id_rename_migration.py": "proves the migration of the old id",
}
OLD_CAMPAIGN_ID_PREFIXES = {
    "docs/archive/": "archived history",
    "tests/fixtures/": "fixture manifests over retained captures",
}
_SCAN_SUFFIXES = {".py", ".json", ".md", ".ps1", ".yml", ".yaml", ".txt", ".toml"}
_SCAN_SKIP_DIRS = {".git", "evidence", ".local-captures", ".local-orchestrator", ".venv", "__pycache__", "node_modules"}

EXECUTION_HANDLERS = {
    "NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE": ("automation_service.nova", "NovaExecutionHandler"),
    "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE": ("automation_service.recruitment", "RecruitmentExecutionHandler"),
    "CAMPAIGN-AP-AUTO-BATTLE": ("automation_service.campaign", "CampaignExecutionHandler"),
    "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION": ("automation_service.bioenhancer", "BioenhancerExecutionHandler"),
    "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION": ("automation_service.supply", "SupplyExecutionHandler"),
    "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION": ("automation_service.ultimate", "UltimateExecutionHandler"),
    "ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION": ("automation_service.enhancement", "EnhancementExecutionHandler"),
    "PERSONAL-MIGHT-PRAISE-BLUESTACKS-INTEGRATION": ("automation_service.personal_might", "PersonalMightExecutionHandler"),
    DAILY_REWARDS_FLOW_ID: ("automation_service.daily_rewards", "DailyRewardsExecutionHandler"),
    RESOURCE_ITEM_FLOW_ID: ("automation_service.resource_item", "ResourceItemExecutionHandler"),
    RUINS_FLOW_ID: ("automation_service.ruins", "RuinsExecutionHandler"),
    ALLIANCE_HELP_FLOW_ID: ("automation_service.alliance_help", "AllianceHelpExecutionHandler"),
    ALLIANCE_DONATION_FLOW_ID: ("automation_service.alliance_donation", "AllianceDonationExecutionHandler"),
    ALLIANCE_SHOP_FLOW_ID: ("automation_service.alliance_shop", "AllianceShopExecutionHandler"),
    DAILY_SHOPS_FLOW_ID: ("automation_service.daily_shops", "DailyShopsExecutionHandler"),
    NANO_MATERIAL_PRODUCTION_FLOW_ID: (
        "automation_service.nano_material_production", "NanoMaterialProductionExecutionHandler",
    ),
    NANOWEAPON_FLOW_ID: ("automation_service.nanoweapon", "NanoweaponExecutionHandler"),
    HERO_DUEL_FLOW_ID: ("automation_service.hero_duel", "HeroDuelExecutionHandler"),
    RECOMMENDED_RESEARCH_FLOW_ID: (
        "automation_service.recommended_research", "RecommendedResearchExecutionHandler",
    ),
    FOOD_FARM_BOOST_FLOW_ID: (
        "automation_service.food_farm_boost", "FoodFarmBoostExecutionHandler",
    ),
}


B_FIXED_RELATIONSHIPS = {
    RUINS_FLOW_ID: {
        "cli_name": "ruins",
        "family": "ruins_challenge",
        "variant": "challenge_then_green_chests",
        "product_id": "ruins_challenge",
        "product_revision": "ruins_challenge-v1",
        "handler_id": "ruins_execution_handler",
        "profile_id": RUINS_PROFILE_ID,
        "mode": "phase_canary",
        "max_inputs": 48,
        "max_actions": 13,
        "adapter": ("automation_service.ruins", "RuinsExecutionHandler"),
        "native": ("scripts.ruins_challenge_bluestacks", {
            "RUINS_FLOW_ID": RUINS_FLOW_ID,
            "RUINS_PRODUCT_ID": "ruins_challenge",
            "RUINS_PRODUCT_REVISION": "ruins_challenge-v1",
            "RUINS_PROFILE_ID": RUINS_PROFILE_ID,
            "MAX_INPUTS": 48,
            "MAX_ACTIONS": 13,
        }),
    },
    ALLIANCE_HELP_FLOW_ID: {
        "cli_name": "alliance-help",
        "family": "alliance_help",
        "variant": "ten_successful_free_requests",
        "product_id": "alliance_help",
        "product_revision": "alliance_help-v1",
        "handler_id": "alliance_help_execution_handler",
        "profile_id": ALLIANCE_HELP_PROFILE_ID,
        "mode": "phase_canary",
        "max_inputs": 20,
        "max_actions": 10,
        "adapter": ("automation_service.alliance_help", "AllianceHelpExecutionHandler"),
        "native": ("scripts.alliance_help_bluestacks", {
            "FLOW_ID": ALLIANCE_HELP_FLOW_ID,
            "PRODUCT_ID": "alliance_help",
            "PRODUCT_REVISION": "alliance_help-v1",
            "PROFILE_ID": ALLIANCE_HELP_PROFILE_ID,
            "MAX_INPUTS": 20,
            "MAX_ACTIONS": 10,
        }),
    },
}
C_FIXED_RELATIONSHIPS = {
    ALLIANCE_DONATION_FLOW_ID: {
        "cli_name": "alliance-donation",
        "family": "alliance_donation",
        "variant": "ten_hot_donations",
        "product_id": "alliance_donation",
        "product_revision": "alliance_donation-v1",
        "handler_id": "alliance_donation_execution_handler",
        "profile_id": ALLIANCE_DONATION_PROFILE_ID,
        "max_inputs": 40,
        "max_actions": 10,
        "adapter": ("automation_service.alliance_donation", "AllianceDonationExecutionHandler"),
        "native": ("scripts.alliance_donation_bluestacks", {
            "FLOW_ID": ALLIANCE_DONATION_FLOW_ID,
            "PRODUCT_ID": "alliance_donation",
            "PRODUCT_REVISION": "alliance_donation-v1",
            "PROFILE_ID": ALLIANCE_DONATION_PROFILE_ID,
            "MAX_INPUTS": 40,
            "MAX_DONATIONS_PER_RESET": 10,
        }),
    },
    ALLIANCE_SHOP_FLOW_ID: {
        "cli_name": "alliance-shop",
        "family": "alliance_shop",
        "variant": "one_weekly_or_other",
        "product_id": "alliance_shop_purchase",
        "product_revision": "alliance_shop_purchase-v2",
        "handler_id": "alliance_shop_execution_handler",
        "profile_id": ALLIANCE_SHOP_PROFILE_ID,
        "max_inputs": 24,
        "max_actions": 1,
        "adapter": ("automation_service.alliance_shop", "AllianceShopExecutionHandler"),
        "native": ("scripts.alliance_shop_bluestacks", {
            "FLOW_ID": ALLIANCE_SHOP_FLOW_ID,
            "PRODUCT_ID": "alliance_shop_purchase",
            "PRODUCT_REVISION": "alliance_shop_purchase-v2",
            "MAX_INPUTS": 24,
        }),
    },
    DAILY_SHOPS_FLOW_ID: {
        "cli_name": "daily-shops",
        "family": "daily_shops",
        "variant": "ruins_and_rare_earth_max",
        "product_id": "daily_shops_purchase",
        "product_revision": "daily_shops_purchase-v1",
        "handler_id": "daily_shops_execution_handler",
        "profile_id": DAILY_SHOPS_PROFILE_ID,
        "max_inputs": 48,
        "max_actions": 2,
        "adapter": ("automation_service.daily_shops", "DailyShopsExecutionHandler"),
        "native": ("scripts.daily_shops_bluestacks", {
            "FLOW_ID": DAILY_SHOPS_FLOW_ID,
            "PRODUCT_ID": "daily_shops_purchase",
            "PRODUCT_REVISION": "daily_shops_purchase-v1",
            "MAX_INPUTS": 48,
            "MAX_ACTIONS": 2,
        }),
    },
}

D_FIXED_RELATIONSHIPS = {
    NANO_MATERIAL_PRODUCTION_FLOW_ID: {
        "cli_name": "nano-material-production",
        "family": "nano_material_production",
        "variant": "six_hour_single_slot",
        "product_id": "nano_material_production",
        "product_revision": "nano_material_production-v1",
        "handler_id": "nano_material_production_execution_handler",
        "profile_id": NANO_MATERIAL_PRODUCTION_PROFILE_ID,
        "mode": "phase_canary",
        "max_inputs": 18,
        "max_actions": 2,
        "cadence": "timer",
        "reset_scoped": False,
        "adapter": (
            "automation_service.nano_material_production",
            "NanoMaterialProductionExecutionHandler",
        ),
        "native": ("scripts.nano_material_production_bluestacks", {
            "FLOW_ID": NANO_MATERIAL_PRODUCTION_FLOW_ID,
            "PRODUCT_ID": "nano_material_production",
            "PRODUCT_REVISION": "nano_material_production-v1",
            "PROFILE_ID": NANO_MATERIAL_PRODUCTION_PROFILE_ID,
            "MAX_INPUTS": 18,
            "MAX_ACTIONS": 2,
            "NANO_MATERIAL_PRODUCTION_DURATION_SECONDS": 21600,
        }),
    },
    NANOWEAPON_FLOW_ID: {
        "cli_name": "nanoweapon",
        "family": "nanoweapon",
        "variant": "normal_craft_100_nano_parts",
        "product_id": "nanoweapon_normal_craft",
        "product_revision": "nanoweapon_normal_craft-v2",
        "handler_id": "nanoweapon_execution_handler",
        "profile_id": NANOWEAPON_PROFILE_ID,
        "mode": "phase_canary",
        "max_inputs": 22,
        "max_actions": 4,
        "cadence": "cooldown_pulse",
        "reset_scoped": True,
        "adapter": ("automation_service.nanoweapon", "NanoweaponExecutionHandler"),
        "native": ("scripts.nanoweapon_bluestacks", {
            "FLOW_ID": NANOWEAPON_FLOW_ID,
            "PRODUCT_ID": "nanoweapon_normal_craft",
            "PRODUCT_REVISION": "nanoweapon_normal_craft-v2",
            "PROFILE_ID": NANOWEAPON_PROFILE_ID,
            "MAX_INPUTS": 22,
            "MAX_ACTIONS": 4,
            "NANO_PARTS_REQUIRED": 100,
            "NORMAL_CRAFT_DURATION_SECONDS": 43200,
        }),
    },
}

E_FIXED_RELATIONSHIPS = {
    HERO_DUEL_FLOW_ID: {
        "cli_name": "hero-duel",
        "family": "hero_duel",
        "variant": "up_to_three_free_entry_flee_cycles",
        "product_id": "hero_duel",
        "product_revision": "hero_duel-v2",
        "handler_id": "hero_duel_execution_handler",
        "profile_id": HERO_DUEL_PROFILE_ID,
        "mode": "phase_canary",
        "max_inputs": 64,
        "max_actions": 3,
        "cadence": "cooldown_pulse",
        "reset_scoped": True,
        "adapter": ("automation_service.hero_duel", "HeroDuelExecutionHandler"),
        "native": ("scripts.hero_duel_bluestacks", {
            "FLOW_ID": HERO_DUEL_FLOW_ID,
            "PRODUCT_ID": "hero_duel",
            "PRODUCT_REVISION": "hero_duel-v2",
            "PROFILE_ID": HERO_DUEL_PROFILE_ID,
            "MAX_INPUTS": 64,
            "MAX_ACTIONS": 3,
        }),
    },
    RECOMMENDED_RESEARCH_FLOW_ID: {
        "cli_name": "recommended-research",
        "family": "recommended_research",
        "variant": "first_displayed_recommendation_idle_affordable_start",
        "product_id": "recommended_research",
        "product_revision": "recommended_research-v1",
        "handler_id": "recommended_research_execution_handler",
        "profile_id": RECOMMENDED_RESEARCH_PROFILE_ID,
        "mode": "phase_canary",
        "max_inputs": 24,
        "max_actions": 1,
        "cadence": "cooldown_pulse",
        "reset_scoped": True,
        "adapter": (
            "automation_service.recommended_research", "RecommendedResearchExecutionHandler",
        ),
        "native": ("scripts.recommended_research_bluestacks", {
            "FLOW_ID": RECOMMENDED_RESEARCH_FLOW_ID,
            "PRODUCT_ID": "recommended_research",
            "PRODUCT_REVISION": "recommended_research-v1",
            "PROFILE_ID": RECOMMENDED_RESEARCH_PROFILE_ID,
            "MAX_INPUTS": 24,
            "MAX_ACTIONS": 1,
        }),
    },
    FOOD_FARM_BOOST_FLOW_ID: {
        "cli_name": "food-farm-boost",
        "family": "food_farm_boost",
        "variant": "one_daily_food_farm_boost",
        "product_id": "food_farm_output_boost",
        "product_revision": "food_farm_output_boost-v1",
        "handler_id": "food_farm_boost_execution_handler",
        "profile_id": FOOD_FARM_BOOST_PROFILE_ID,
        "mode": "phase_canary",
        "max_inputs": 16,
        "max_actions": 2,
        "cadence": "cooldown_pulse",
        "reset_scoped": True,
        "adapter": ("automation_service.food_farm_boost", "FoodFarmBoostExecutionHandler"),
        "native": ("scripts.food_farm_boost_bluestacks", {
            "FLOW_ID": FOOD_FARM_BOOST_FLOW_ID,
            "PRODUCT_ID": "food_farm_output_boost",
            "PRODUCT_REVISION": "food_farm_output_boost-v1",
            "MAX_INPUTS": 16,
            "MAX_ACTIONS": 2,
        }),
    },
}


# Every non-registry copy of a service route's input budget: (module, attribute).
MAX_INPUT_COPIES = {
    "RECRUITMENT-FREE-ATTEMPT-MAINTENANCE": [("scripts.flow_delivery_recruitment_bluestacks", "MAX_INPUTS")],
    "CAMPAIGN-AP-AUTO-BATTLE": [
        ("scripts.flow_delivery_campaign_bluestacks", "MAX_INPUTS"),
        ("tasks.campaign_auto_battle", "CAMPAIGN_MAX_INPUTS"),
    ],
    "BIOENHANCER-FREE-RESEARCH-BLUESTACKS-INTEGRATION": [("scripts.flow_delivery_bioenhancer_bluestacks", "MAX_INPUTS")],
    "SUPPLY-DEPOT-BLUESTACKS-INTEGRATION": [("scripts.flow_delivery_supply_depot_bluestacks", "MAX_INPUTS")],
    "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION": [
        ("scripts.flow_delivery_ultimate_challenge_bluestacks", "MAX_TOTAL_INPUTS"),
        ("scripts.bluestacks_ultimate_challenge", "MAX_TOTAL_INPUTS"),
    ],
    "PERSONAL-MIGHT-PRAISE-BLUESTACKS-INTEGRATION": [("scripts.flow_delivery_personal_might_bluestacks", "MAX_INPUTS")],
    RESOURCE_ITEM_FLOW_ID: [
        ("scripts.daily_resource_item_bluestacks", "MAX_ROUTE_INPUTS"),
    ],
    ALLIANCE_HELP_FLOW_ID: [("scripts.alliance_help_bluestacks", "MAX_INPUTS")],
    ALLIANCE_DONATION_FLOW_ID: [
        ("automation_service.alliance_donation", "MAX_INPUTS"),
        ("scripts.alliance_donation_bluestacks", "MAX_INPUTS"),
    ],
    ALLIANCE_SHOP_FLOW_ID: [
        ("automation_service.alliance_shop", "MAX_INPUTS"),
        ("scripts.alliance_shop_bluestacks", "MAX_INPUTS"),
    ],
    DAILY_SHOPS_FLOW_ID: [
        ("automation_service.daily_shops", "MAX_INPUTS"),
        ("scripts.daily_shops_bluestacks", "MAX_INPUTS"),
    ],
    NANO_MATERIAL_PRODUCTION_FLOW_ID: [
        ("automation_service.nano_material_production", "MAX_INPUTS"),
        ("scripts.nano_material_production_bluestacks", "MAX_INPUTS"),
    ],
    NANOWEAPON_FLOW_ID: [
        ("automation_service.nanoweapon", "MAX_INPUTS"),
        ("scripts.nanoweapon_bluestacks", "MAX_INPUTS"),
    ],

    HERO_DUEL_FLOW_ID: [
        ("automation_service.hero_duel", "MAX_INPUTS"),
        ("scripts.hero_duel_bluestacks", "MAX_INPUTS"),
    ],
    RECOMMENDED_RESEARCH_FLOW_ID: [
        ("automation_service.recommended_research", "MAX_INPUTS"),
        ("scripts.recommended_research_bluestacks", "MAX_INPUTS"),
    ],
    FOOD_FARM_BOOST_FLOW_ID: [
        ("automation_service.food_farm_boost", "MAX_INPUTS"),
        ("scripts.food_farm_boost_bluestacks", "MAX_INPUTS"),
    ],
}

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18,
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _code_ids() -> set[str]:
    return {entry.flow_id for entry in CANONICAL_FLOW_REGISTRY}


def _operator_ids() -> set[str]:
    return set(_read_json(TASKS / "flow_delivery_bluestacks_registry.json")["flows"])


def _disabled_ids() -> set[str]:
    return {entry.flow_id for entry in load_disabled_registry()}


def _queue() -> dict:
    return _read_json(TASKS / "flow_delivery_queue.json")


def _queue_ids() -> set[str]:
    return {flow["flow_id"] for flow in _queue()["flows"]}


def _contract_ids() -> set[str]:
    return set(list_flow_contract_ids())


class RouteTestCase(unittest.TestCase):
    def assertSubsetIds(self, small: set[str], big: set[str], small_name: str, big_name: str, allowed=()) -> None:
        missing = sorted(small - big - set(allowed))
        self.assertFalse(
            missing,
            f"flow ids in the {small_name} but absent from the {big_name}: {missing}\n"
            f"  {small_name}={sorted(small)}\n  {big_name}={sorted(big)}",
        )


class FlowIdSetRelationTests(RouteTestCase):
    def test_code_registry_routes_exist_in_every_other_authority(self) -> None:
        code = _code_ids()
        self.assertSubsetIds(code, _disabled_ids(), "code registry", "disabled-production registry")
        self.assertSubsetIds(code, _queue_ids(), "code registry", "development queue")
        self.assertSubsetIds(code, _contract_ids(), "code registry", "gameplay contracts")
        self.assertSubsetIds(code, _operator_ids(), "code registry", "operator registry", allowed=NO_OPERATOR_RUNNER)

    def test_operator_registry_routes_exist_in_queue_contracts_and_disabled_registry(self) -> None:
        operator = _operator_ids()
        self.assertSubsetIds(operator, _queue_ids(), "operator registry", "development queue")
        self.assertSubsetIds(operator, _contract_ids(), "operator registry", "gameplay contracts")
        self.assertSubsetIds(operator, _disabled_ids(), "operator registry", "disabled-production registry")

    def test_queue_and_disabled_registry_flows_all_have_contracts(self) -> None:
        self.assertSubsetIds(_queue_ids(), _contract_ids(), "development queue", "gameplay contracts")
        self.assertSubsetIds(_disabled_ids(), _contract_ids(), "disabled-production registry", "gameplay contracts")
        self.assertSubsetIds(_disabled_ids(), _queue_ids(), "disabled-production registry", "development queue")

    def test_every_contract_is_queued_or_explicitly_historical(self) -> None:
        self.assertSubsetIds(_contract_ids(), _queue_ids(), "gameplay contracts", "development queue", allowed=CONTRACT_ONLY_FLOWS)
        for flow_id in CONTRACT_ONLY_FLOWS:
            with self.subTest(flow_id=flow_id):
                self.assertIn(flow_id, _contract_ids(), "stale CONTRACT_ONLY_FLOWS entry")
                self.assertNotIn(flow_id, _queue_ids() | _code_ids(), "listed as contract-only but now routed")

    def test_exception_tables_have_no_stale_entries(self) -> None:
        self.assertEqual(set(NO_OPERATOR_RUNNER) & _operator_ids(), set(), "NO_OPERATOR_RUNNER lists a flow that has a runner")
        self.assertSubsetIds(set(NO_OPERATOR_RUNNER), _code_ids(), "NO_OPERATOR_RUNNER", "code registry")
        stale = set(NO_DEFAULT_MAX_INPUTS) & set(pnsctl._DEFAULT_MAX_INPUTS)
        self.assertEqual(stale, set(), f"NO_DEFAULT_MAX_INPUTS lists flows that now have a default: {sorted(stale)}")

    def test_pnsctl_selectable_flows_are_exactly_the_operator_registry(self) -> None:
        self.assertEqual(
            set(pnsctl.BLUESTACKS_FLOW_IDS),
            _operator_ids(),
            "a flow in tasks/flow_delivery_bluestacks_registry.json has no runner/validator/recovery bound in code (or the reverse)",
        )

    def test_development_session_defaults_cover_exactly_the_operator_flows_with_a_budget(self) -> None:
        operator = _operator_ids()
        defaults = set(pnsctl._DEFAULT_MAX_INPUTS)
        self.assertSubsetIds(defaults, operator, "pnsctl._DEFAULT_MAX_INPUTS", "operator registry")
        self.assertSubsetIds(operator, defaults, "operator registry", "pnsctl._DEFAULT_MAX_INPUTS", allowed=NO_DEFAULT_MAX_INPUTS)

    def test_registry_has_unique_ids_cli_names_and_family_variants(self) -> None:
        entries = CANONICAL_FLOW_REGISTRY
        for label, values in (
            ("flow id", [e.flow_id for e in entries]),
            ("family", [e.descriptor.family for e in entries]),
            ("product id", [e.product_id for e in entries]),
            ("handler id", [e.handler_id for e in entries]),
            ("cli name", [e.cli_name for e in entries if e.cli_name is not None]),
        ):
            self.assertEqual(len(values), len(set(values)), f"duplicate {label} in CANONICAL_FLOW_REGISTRY: {values}")

    def test_migration_targets_are_the_registered_campaign_id(self) -> None:
        self.assertEqual(
            {new for _old, new in state_module.RENAMED_FLOW_IDS} | {new for _old, new in store_module.RENAMED_TASK_IDS},
            {CAMPAIGN_FLOW_ID},
        )
        self.assertEqual(safe_policy.CAMPAIGN_AP_FLOW_ID, CAMPAIGN_FLOW_ID)
        self.assertEqual(pnsctl.CAMPAIGN_AP_FLOW_ID, CAMPAIGN_FLOW_ID)


def _scan_old_campaign_id() -> set[str]:
    hits: set[str] = set()
    for directory, subdirs, names in os.walk(ROOT):
        subdirs[:] = [name for name in subdirs if name not in _SCAN_SKIP_DIRS]
        for name in names:
            path = Path(directory) / name
            if path.suffix not in _SCAN_SUFFIXES or path == Path(__file__).resolve():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if OLD_CAMPAIGN_ID in text:
                hits.add(path.relative_to(ROOT).as_posix())
    return hits


class RetainedCampaignIdTests(RouteTestCase):
    def test_old_campaign_id_survives_only_in_the_allowlisted_places(self) -> None:
        unexpected = sorted(
            path
            for path in _scan_old_campaign_id()
            if path not in OLD_CAMPAIGN_ID_FILES and not path.startswith(tuple(OLD_CAMPAIGN_ID_PREFIXES))
        )
        self.assertFalse(
            unexpected,
            f"{OLD_CAMPAIGN_ID} (renamed to {CAMPAIGN_FLOW_ID} in #36) appears outside the allowlist: {unexpected}. "
            "Rename it, or add the file to OLD_CAMPAIGN_ID_FILES with a reason if it is retained history.",
        )

    def test_allowlisted_files_still_need_their_entry(self) -> None:
        for relative in OLD_CAMPAIGN_ID_FILES:
            with self.subTest(path=relative):
                path = ROOT / relative
                self.assertTrue(path.is_file(), f"stale allowlist entry, file is gone: {relative}")
                self.assertIn(OLD_CAMPAIGN_ID, path.read_text(encoding="utf-8"), f"stale allowlist entry: {relative}")


class ProductBindingTests(RouteTestCase):
    def test_contract_bindings_match_the_product_policy_records(self) -> None:
        # Same vocabulary on both sides: a contract binding names a policy record and its revision/digest.
        validate_contract_product_authority_bindings(load_product_authority(), load_all_flow_contracts())

    def test_registry_snapshot_descriptor_and_adapter_agree_per_route(self) -> None:
        for flow_id, (module_name, class_name) in EXECUTION_HANDLERS.items():
            with self.subTest(flow_id=flow_id):
                entry = canonical_entry(flow_id)
                self.assertEqual(entry.registration.flow_id, flow_id)
                self.assertEqual(entry.descriptor.accepted_product, entry.product_id)
                self.assertEqual(entry.descriptor.product_revision, entry.product_revision)
                module = import_module(module_name)
                handler = getattr(module, class_name)(entry.registration, lambda *args, **kwargs: None)
                described = handler.describe()
                expected = entry.descriptor
                if described.allows_pending_resource_observation:
                    # Campaign opts in to pending-resource observation; every other fact is the registry's.
                    from dataclasses import replace

                    expected = replace(expected, allows_pending_resource_observation=True)
                self.assertEqual(
                    described,
                    expected,
                    f"{module_name}.{class_name}.describe() re-spells registry facts for {flow_id}",
                )
                for constant, value in (("PRODUCT_ID", entry.product_id), ("PRODUCT_REVISION", entry.product_revision)):
                    if hasattr(module, constant):
                        self.assertEqual(getattr(module, constant), value, f"{module_name}.{constant} drifted from the registry")

    def test_batch_b_fixed_relationships_and_canonical_only_retirement(self) -> None:
        self.assertEqual(set(B_FIXED_RELATIONSHIPS), {RUINS_FLOW_ID, ALLIANCE_HELP_FLOW_ID})
        self.assertNotIn(RUINS_FLOW_ID, MAX_INPUT_COPIES)
        operator = _operator_ids()
        for flow_id, expected in B_FIXED_RELATIONSHIPS.items():
            with self.subTest(flow_id=flow_id):
                entry = canonical_entry(flow_id)
                self.assertEqual(entry.cli_name, expected["cli_name"])
                self.assertEqual(entry.descriptor.family, expected["family"])
                self.assertEqual(
                    (entry.product_id, entry.product_revision, entry.handler_id),
                    (expected["product_id"], expected["product_revision"], expected["handler_id"]),
                )
                self.assertEqual(
                    (entry.registration.production_handler, entry.registration.profile, entry.registration.mode),
                    (expected["handler_id"], expected["profile_id"], expected["mode"]),
                )
                self.assertEqual(
                    (entry.registration.registration_status, entry.registration.scheduler_eligible),
                    ("REGISTERED", True),
                )
                self.assertEqual(
                    (entry.max_inputs, entry.descriptor.variant, entry.descriptor.cadence, entry.descriptor.reset_scoped),
                    (expected["max_inputs"], expected["variant"], "cooldown_pulse", True),
                )
                adapter_module, class_name = expected["adapter"]
                adapter = import_module(adapter_module)
                self.assertEqual(
                    (adapter.PRODUCT_ID, adapter.PRODUCT_REVISION, adapter.PROFILE_ID,
                     adapter.MAX_INPUTS, adapter.MAX_ACTIONS),
                    (expected["product_id"], expected["product_revision"], expected["profile_id"],
                     expected["max_inputs"], expected["max_actions"]),
                )
                self.assertEqual(getattr(adapter, class_name).max_inputs, expected["max_inputs"])
                native_module, native_facts = expected["native"]
                native = import_module(native_module)
                for attribute, value in native_facts.items():
                    self.assertEqual(getattr(native, attribute), value, f"{native_module}.{attribute} drifted")
                self.assertNotIn(flow_id, operator)
                self.assertNotIn(flow_id, pnsctl.BLUESTACKS_FLOW_IDS)
                self.assertNotIn(flow_id, pnsctl._DEFAULT_MAX_INPUTS)
                self.assertIn("canonical", NO_OPERATOR_RUNNER[flow_id].casefold())

    def test_batch_c_routes_keep_frozen_identities_and_no_operator_runners(self) -> None:
        self.assertEqual(set(C_FIXED_RELATIONSHIPS), {
            ALLIANCE_DONATION_FLOW_ID, ALLIANCE_SHOP_FLOW_ID, DAILY_SHOPS_FLOW_ID,
        })
        operator = _operator_ids()
        self.assertEqual(len(operator), 12, "Batch C adds canonical-only service routes, not operator runners")
        queue = {flow["flow_id"]: flow for flow in _queue()["flows"]}
        for flow_id, expected in C_FIXED_RELATIONSHIPS.items():
            queue_record = queue[flow_id]
            with self.subTest(flow_id=flow_id):
                entry = canonical_entry(flow_id)
                self.assertEqual(
                    (
                        queue_record["status"], queue_record["production_registration"],
                        queue_record["scheduler_enabled"], queue_record["product_policy_status"],
                    ),
                    ("evidence_required", "NOT_REGISTERED", False, "explicitly_approved"),
                )
                self.assertEqual(
                    (
                        queue_record["maximum_inputs"], queue_record["maximum_live_inputs"],
                        queue_record["maximum_live_attempts"], queue_record["live_attempt_count"],
                    ),
                    (expected["max_inputs"], expected["max_inputs"], 0, 0),
                )
                self.assertEqual(queue_record["live_attempts"], [])
                adapter_module, _ = expected["adapter"]
                native_module, _ = expected["native"]
                required_paths = {
                    adapter_module.replace(".", "/") + ".py",
                    native_module.replace(".", "/") + ".py",
                    f"tests/test_service_{expected['family']}.py",
                    f"tests/test_{native_module.rsplit('.', 1)[-1]}.py",
                    "tests/test_service_route_contract.py",
                    "tests/test_route_metadata_consistency.py",
                }
                self.assertTrue(
                    required_paths <= (
                        set(queue_record["implementation_entrypoints"])
                        | set(queue_record["focused_tests"])
                    ),
                )
                self.assertEqual(entry.cli_name, expected["cli_name"])
                self.assertEqual(entry.descriptor.family, expected["family"])
                self.assertEqual(entry.descriptor.variant, expected["variant"])
                self.assertEqual(
                    (entry.product_id, entry.product_revision, entry.handler_id),
                    (expected["product_id"], expected["product_revision"], expected["handler_id"]),
                )
                self.assertEqual(
                    (entry.registration.production_handler, entry.registration.profile, entry.registration.mode),
                    (expected["handler_id"], expected["profile_id"], "phase_canary"),
                )
                self.assertEqual(
                    (entry.registration.registration_status, entry.registration.scheduler_eligible),
                    ("REGISTERED", True),
                )
                self.assertEqual(
                    (entry.max_inputs, entry.descriptor.cadence, entry.descriptor.reset_scoped,
                     entry.descriptor.recurrence_class),
                    (expected["max_inputs"], "cooldown_pulse", True, RecurrenceClass.COOLDOWN),
                )
                adapter_module, class_name = expected["adapter"]
                adapter = import_module(adapter_module)
                self.assertEqual(
                    (adapter.PRODUCT_ID, adapter.PRODUCT_REVISION, adapter.PROFILE_ID,
                     adapter.MAX_INPUTS, adapter.MAX_ACTIONS),
                    (expected["product_id"], expected["product_revision"], expected["profile_id"],
                     expected["max_inputs"], expected["max_actions"]),
                )
                handler = getattr(adapter, class_name)
                self.assertEqual(handler.max_inputs, expected["max_inputs"])
                self.assertEqual(handler.max_actions, expected["max_actions"])
                native_module, native_facts = expected["native"]
                native = import_module(native_module)
                for attribute, value in native_facts.items():
                    self.assertEqual(getattr(native, attribute), value, f"{native_module}.{attribute} drifted")
                self.assertNotIn(flow_id, operator)
                self.assertNotIn(flow_id, pnsctl.BLUESTACKS_FLOW_IDS)
                self.assertNotIn(flow_id, pnsctl._DEFAULT_MAX_INPUTS)
                self.assertIn("canonical", NO_OPERATOR_RUNNER[flow_id].casefold())

    def test_batch_d_routes_have_current_native_adapters_and_no_operator_runners(self) -> None:
        self.assertEqual(set(D_FIXED_RELATIONSHIPS), {
            NANO_MATERIAL_PRODUCTION_FLOW_ID, NANOWEAPON_FLOW_ID,
        })
        operator = _operator_ids()
        self.assertEqual(len(operator), 12, "Batch D preserves the existing operator routes")
        queue = {flow["flow_id"]: flow for flow in _queue()["flows"]}
        for flow_id, expected in D_FIXED_RELATIONSHIPS.items():
            queue_record = queue[flow_id]
            with self.subTest(flow_id=flow_id):
                self.assertEqual(
                    (
                        queue_record["status"], queue_record["production_registration"],
                        queue_record["scheduler_enabled"], queue_record["product_policy_status"],
                    ),
                    ("evidence_required", "NOT_REGISTERED", False, "explicitly_approved"),
                )
                self.assertEqual(
                    (
                        queue_record["maximum_inputs"], queue_record["maximum_live_inputs"],
                        queue_record["maximum_actions"], queue_record["maximum_live_attempts"],
                        queue_record["live_attempt_count"],
                    ),
                    (expected["max_inputs"], expected["max_inputs"], expected["max_actions"], 0, 0),
                )
                self.assertEqual(queue_record["live_attempts"], [])
                adapter_module, class_name = expected["adapter"]
                native_module, native_facts = expected["native"]
                required_paths = {
                    adapter_module.replace(".", "/") + ".py",
                    native_module.replace(".", "/") + ".py",
                    f"tests/test_service_{expected['family']}.py",
                    f"tests/test_{native_module.rsplit('.', 1)[-1]}.py",
                    "tests/test_service_route_contract.py",
                    "tests/test_route_metadata_consistency.py",
                }
                self.assertTrue(
                    required_paths <= (
                        set(queue_record["implementation_entrypoints"])
                        | set(queue_record["focused_tests"])
                    ),
                )
                entry = canonical_entry(flow_id)
                self.assertEqual(
                    (entry.cli_name, entry.descriptor.family, entry.descriptor.variant),
                    (expected["cli_name"], expected["family"], expected["variant"]),
                )
                self.assertEqual(
                    (entry.product_id, entry.product_revision, entry.handler_id),
                    (expected["product_id"], expected["product_revision"], expected["handler_id"]),
                )
                self.assertEqual(
                    (entry.registration.production_handler, entry.registration.profile,
                     entry.registration.mode, entry.registration.registration_status,
                     entry.registration.scheduler_eligible),
                    (
                        expected["handler_id"], expected["profile_id"], expected["mode"],
                        "REGISTERED", True,
                    ),
                )
                self.assertEqual(
                    (entry.max_inputs, entry.descriptor.cadence,
                     entry.descriptor.reset_scoped, entry.descriptor.recurrence_class),
                    (
                        expected["max_inputs"], expected["cadence"], expected["reset_scoped"],
                        RecurrenceClass.TIMER if expected["cadence"] == "timer"
                        else RecurrenceClass.COOLDOWN,
                    ),
                )
                adapter = import_module(adapter_module)
                self.assertEqual(
                    (adapter.PRODUCT_ID, adapter.PRODUCT_REVISION, adapter.PROFILE_ID,
                     adapter.MAX_INPUTS, adapter.MAX_ACTIONS),
                    (expected["product_id"], expected["product_revision"], expected["profile_id"],
                     expected["max_inputs"], expected["max_actions"]),
                )
                handler = getattr(adapter, class_name)
                self.assertEqual(
                    (handler.max_inputs, handler.max_actions),
                    (expected["max_inputs"], expected["max_actions"]),
                )
                native = import_module(native_module)
                for attribute, value in native_facts.items():
                    self.assertEqual(getattr(native, attribute), value, f"{native_module}.{attribute} drifted")
                self.assertNotIn(flow_id, operator)
                self.assertNotIn(flow_id, pnsctl.BLUESTACKS_FLOW_IDS)
                self.assertNotIn(flow_id, pnsctl._DEFAULT_MAX_INPUTS)

    def test_batch_e_routes_keep_evidence_gates_and_native_contracts(self) -> None:
        self.assertEqual(set(E_FIXED_RELATIONSHIPS), {
            HERO_DUEL_FLOW_ID, RECOMMENDED_RESEARCH_FLOW_ID, FOOD_FARM_BOOST_FLOW_ID,
        })
        operator = _operator_ids()
        self.assertEqual(len(operator), 12, "Batch E keeps all legacy operator choices unchanged")
        queue = {flow["flow_id"]: flow for flow in _queue()["flows"]}
        for flow_id, expected in E_FIXED_RELATIONSHIPS.items():
            queue_record = queue[flow_id]
            with self.subTest(flow_id=flow_id):
                self.assertEqual(
                    (
                        queue_record["status"], queue_record["production_registration"],
                        queue_record["scheduler_enabled"], queue_record["product_policy_status"],
                    ),
                    ("evidence_required", "NOT_REGISTERED", False, "explicitly_approved"),
                )
                self.assertEqual(
                    (
                        queue_record["maximum_inputs"], queue_record["maximum_live_inputs"],
                        queue_record["maximum_actions"], queue_record["maximum_live_attempts"],
                        queue_record["live_attempt_count"], queue_record["live_attempts"],
                    ),
                    (
                        expected["max_inputs"], expected["max_inputs"], expected["max_actions"],
                        0, 0, [],
                    ),
                )
                entry = canonical_entry(flow_id)
                self.assertEqual(
                    (entry.cli_name, entry.descriptor.family, entry.descriptor.variant),
                    (expected["cli_name"], expected["family"], expected["variant"]),
                )
                self.assertEqual(
                    (entry.product_id, entry.product_revision, entry.handler_id),
                    (expected["product_id"], expected["product_revision"], expected["handler_id"]),
                )
                self.assertEqual(
                    (
                        entry.registration.production_handler, entry.registration.profile,
                        entry.registration.mode, entry.registration.registration_status,
                        entry.registration.scheduler_eligible, entry.spec.default_enabled,
                    ),
                    (
                        expected["handler_id"], expected["profile_id"], expected["mode"],
                        "REGISTERED", True, False,
                    ),
                )
                self.assertEqual(
                    (entry.max_inputs, entry.descriptor.cadence, entry.descriptor.reset_scoped,
                     entry.descriptor.recurrence_class),
                    (
                        expected["max_inputs"], "cooldown_pulse", True,
                        RecurrenceClass.COOLDOWN,
                    ),
                )
                adapter_module, class_name = expected["adapter"]
                adapter = import_module(adapter_module)
                self.assertEqual(
                    (adapter.PRODUCT_ID, adapter.PRODUCT_REVISION, adapter.PROFILE_ID,
                     adapter.MAX_INPUTS, adapter.MAX_ACTIONS),
                    (
                        expected["product_id"], expected["product_revision"],
                        expected["profile_id"], expected["max_inputs"], expected["max_actions"],
                    ),
                )
                handler = getattr(adapter, class_name)
                self.assertEqual(
                    (handler.max_inputs, handler.max_actions),
                    (expected["max_inputs"], expected["max_actions"]),
                )
                native_module, native_facts = expected["native"]
                native = import_module(native_module)
                for attribute, value in native_facts.items():
                    self.assertEqual(getattr(native, attribute), value)
                required_paths = {
                    adapter_module.replace(".", "/") + ".py",
                    native_module.replace(".", "/") + ".py",
                    f"tests/test_service_{expected['family']}.py",
                    f"tests/test_{native_module.rsplit('.', 1)[-1]}.py",
                    "tests/test_service_route_contract.py",
                    "tests/test_route_metadata_consistency.py",
                }
                self.assertTrue(
                    required_paths <= (
                        set(queue_record["implementation_entrypoints"])
                        | set(queue_record["focused_tests"])
                    ),
                )
                self.assertNotIn(flow_id, operator)
                self.assertNotIn(flow_id, pnsctl.BLUESTACKS_FLOW_IDS)
                self.assertNotIn(flow_id, pnsctl._DEFAULT_MAX_INPUTS)
                self.assertIn("canonical", NO_OPERATOR_RUNNER[flow_id].casefold())

    def test_selection_handlers_describe_the_registry_cadence(self) -> None:
        for entry in CANONICAL_FLOW_REGISTRY:
            if entry.registration_status != "REGISTERED":
                continue
            with self.subTest(flow_id=entry.flow_id):
                handler = entry.build_handler()
                described = handler.describe()
                self.assertEqual(
                    (described.family, described.variant, described.cadence, described.reset_scoped),
                    (entry.descriptor.family, entry.descriptor.variant, entry.descriptor.cadence, entry.descriptor.reset_scoped),
                )

    def test_campaign_safety_policy_names_the_registry_campaign_revision(self) -> None:
        # safe_action_core may not import automation_service (layering), so it keeps its own copy of the
        # value it compares against ``PolicyRequest.action_kind``; the two must stay identical.
        self.assertEqual(safe_policy.CAMPAIGN_AP_PRODUCT_REVISION, CAMPAIGN_PRODUCT_REVISION)


class MaxInputTests(RouteTestCase):
    def test_every_executable_route_has_a_registry_budget_and_its_handler_uses_it(self) -> None:
        for flow_id, (module_name, class_name) in EXECUTION_HANDLERS.items():
            with self.subTest(flow_id=flow_id):
                budget = canonical_entry(flow_id).max_inputs
                self.assertIsInstance(budget, int, f"{flow_id} has no registry max_inputs")
                self.assertEqual(getattr(import_module(module_name), class_name).max_inputs, budget)
        non_executable = [e.flow_id for e in CANONICAL_FLOW_REGISTRY if e.flow_id not in EXECUTION_HANDLERS]
        for flow_id in non_executable:
            self.assertIsNone(canonical_entry(flow_id).max_inputs, f"{flow_id} has a budget but no execution handler")

    def test_native_and_adapter_copies_equal_the_registry_budget(self) -> None:
        for flow_id, copies in MAX_INPUT_COPIES.items():
            budget = canonical_entry(flow_id).max_inputs
            for module_name, attribute in copies:
                with self.subTest(flow_id=flow_id, copy=f"{module_name}.{attribute}"):
                    self.assertEqual(getattr(import_module(module_name), attribute), budget)
        for flow_id, (module_name, _class_name) in EXECUTION_HANDLERS.items():
            module = import_module(module_name)
            if hasattr(module, "MAX_INPUTS"):
                with self.subTest(adapter=module_name):
                    self.assertEqual(module.MAX_INPUTS, canonical_entry(flow_id).max_inputs)

    def test_pnsctl_development_defaults_equal_the_budget_owner(self) -> None:
        defaults = pnsctl._DEFAULT_MAX_INPUTS
        for entry in CANONICAL_FLOW_REGISTRY:
            if entry.flow_id not in defaults or entry.flow_id in DEFAULT_MAX_INPUTS_DIFFERS_FROM_REGISTRY:
                continue
            with self.subTest(flow_id=entry.flow_id):
                self.assertEqual(defaults[entry.flow_id], entry.max_inputs, "pnsctl._DEFAULT_MAX_INPUTS drifted from the registry")
        self.assertEqual(
            set(DEFAULT_MAX_INPUTS_DIFFERS_FROM_REGISTRY) - set(defaults), set(), "stale DEFAULT_MAX_INPUTS_DIFFERS_FROM_REGISTRY"
        )
        for flow_id in DEFAULT_MAX_INPUTS_DIFFERS_FROM_REGISTRY:
            self.assertNotEqual(defaults[flow_id], canonical_entry(flow_id).max_inputs, f"{flow_id} exception no longer needed")

    def test_batch_a_routes_are_canonical_only_and_resource_copies_agree(self) -> None:
        from scripts import daily_resource_item_bluestacks as resource_route
        from scripts import flow_delivery_troop_training_bluestacks as troop_delivery

        queue = {flow["flow_id"]: flow for flow in _queue()["flows"]}
        staging = {
            entry["execution_flow_id"]: entry
            for entry in _queue()["portfolio_staging"]["entries"]
            if entry.get("execution_flow_id")
        }
        contracts = load_all_flow_contracts()
        defaults = pnsctl._DEFAULT_MAX_INPUTS
        operator = _operator_ids()
        for flow_id in (DAILY_REWARDS_FLOW_ID, RESOURCE_ITEM_FLOW_ID):
            with self.subTest(flow_id=flow_id):
                self.assertNotIn(flow_id, operator)
                self.assertNotIn(flow_id, pnsctl.BLUESTACKS_FLOW_IDS)
                self.assertNotIn(flow_id, defaults)

        resource = RESOURCE_ITEM_FLOW_ID
        resource_budget = canonical_entry(resource).max_inputs
        copies = {
            "route MAX_ROUTE_INPUTS": resource_route.MAX_ROUTE_INPUTS,
            "contract navigation_input_authorization": contracts[resource]["navigation_input_authorization"]["maximum_inputs"],
            "queue maximum_inputs": queue[resource]["maximum_inputs"],
            "queue maximum_live_inputs": queue[resource]["maximum_live_inputs"],
            "queue staging maximum_inputs": staging[resource]["maximum_inputs"],
        }
        for name, value in copies.items():
            with self.subTest(flow_id=resource, copy=name):
                self.assertEqual(value, resource_budget, f"Daily Resource Item {name} drifted from the registry")
        self.assertEqual(
            queue[resource]["maximum_resource_list_swipes"],
            resource_route.MAX_RESOURCE_LIST_SWIPES,
        )
        self.assertEqual(
            staging[resource]["maximum_resource_list_swipes"],
            resource_route.MAX_RESOURCE_LIST_SWIPES,
        )

        troop = troop_delivery.FLOW_ID
        self.assertEqual(defaults[troop], troop_delivery.MAX_INPUTS)
        self.assertEqual(
            queue[troop]["development_session_max_inputs"], troop_delivery.MAX_INPUTS,
        )


class ServeWiringTests(RouteTestCase):
    def test_cli_flow_choices_are_exactly_the_registry_names(self) -> None:
        subparsers = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
        flow = next(a for a in subparsers.choices["serve"]._actions if "--flow" in a.option_strings)
        self.assertEqual(set(flow.choices), set(servable_flow_names()))

    def test_every_servable_route_has_a_handler_row_and_a_service_runner(self) -> None:
        self.assertEqual(set(servable_flow_names().values()), set(EXECUTION_HANDLERS), "add the new route to EXECUTION_HANDLERS")
        constructor = AutomationService.__init__.__code__.co_varnames
        for cli_name in servable_flow_names():
            with self.subTest(cli_name=cli_name):
                self.assertIn(_runner_attribute(cli_name), constructor)

    def test_navigation_only_registrations_are_exactly_the_unservable_ones(self) -> None:
        unservable = {e.flow_id for e in CANONICAL_FLOW_REGISTRY if e.cli_name is None}
        navigation_only = {e.flow_id for e in CANONICAL_FLOW_REGISTRY if e.descriptor.variant == NAVIGATION_ONLY}
        self.assertEqual(unservable, navigation_only)


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if match is None:
        raise AssertionError(f"README has no '## {heading}' section")
    return match.group(1)


def _route_rows(text: str) -> list[tuple[str | None, str]]:
    """Return (serve flow or None, registry family) for each README route-table row."""

    rows = []
    for line in _section(text, "Routes").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) < 2 or set(cells[0]) <= {"-", " "}:
            continue
        if cells[0] == "`serve --flow`":
            continue
        family = re.fullmatch(r"`([a-z0-9_]+)`", cells[1])
        if family is None:
            raise AssertionError(f"route row has no backticked registry family: {line}")
        flow = re.fullmatch(r"`([a-z0-9-]+)`", cells[0])
        if flow is None and "navigation-only" not in cells[0]:
            raise AssertionError(f"route row has neither a --flow name nor navigation-only: {line}")
        rows.append((flow.group(1) if flow else None, family.group(1)))
    return rows


def _counts(text: str, pattern: str) -> list[int]:
    found = []
    for word in re.findall(pattern, text, re.I):
        lowered = word.lower()
        found.append(int(lowered) if lowered.isdigit() else _NUMBER_WORDS[lowered])
    return found


class DocumentedRouteTests(RouteTestCase):
    def setUp(self) -> None:
        self.readme = README.read_text(encoding="utf-8")
        self.rows = _route_rows(self.readme)

    def test_readme_route_table_has_one_row_per_registry_family(self) -> None:
        families = [family for _, family in self.rows]
        self.assertEqual(len(families), len(set(families)), "duplicate route rows in README")
        self.assertEqual(set(families), {e.descriptor.family for e in CANONICAL_FLOW_REGISTRY})

    def test_readme_serve_names_match_the_registry(self) -> None:
        self.assertEqual({flow for flow, _ in self.rows if flow is not None}, set(servable_flow_names()))
        navigation_only = {e.descriptor.family for e in CANONICAL_FLOW_REGISTRY if e.cli_name is None}
        self.assertEqual({family for flow, family in self.rows if flow is None}, navigation_only)
        example = set(re.findall(r"--flow ([a-z0-9-]+)", _section(self.readme, "Running")))
        self.assertEqual(example, set(servable_flow_names()), "README's all-routes serve example is out of date")

    def test_documented_route_counts_match_the_registry(self) -> None:
        servable = len(servable_flow_names())
        registered = len(CANONICAL_FLOW_REGISTRY)
        automation = AUTOMATION_DOC.read_text(encoding="utf-8")
        for name, text, pattern, expected in (
            ("docs/automation-service.md 'N fixed flow specs'", automation, r"\b(\w+) fixed flow specs", registered),
            ("docs/automation-service.md 'N-route command'", automation, r"\b(\w+)-route command", servable),
        ):
            with self.subTest(doc=name):
                counts = _counts(text, pattern)
                self.assertTrue(counts, f"{name}: the sentence the test checks is gone; update the test with the doc")
                self.assertEqual(counts, [expected] * len(counts), f"{name} disagrees with the registry ({expected})")
        self.assertEqual(
            len(self.rows), registered, f"README route table has {len(self.rows)} rows, registry has {registered}"
        )


class QueuePathTests(RouteTestCase):
    def test_every_current_queue_file_reference_exists(self) -> None:
        missing = []
        for flow in _queue()["flows"]:
            for key in QUEUE_PATH_KEYS:
                for reference in flow.get(key, []):
                    if not (ROOT / reference).exists():
                        missing.append(f"{flow['flow_id']}.{key}: {reference}")
        self.assertFalse(
            missing,
            "tasks/flow_delivery_queue.json names files that do not exist (historical records belong in "
            "live_attempts/retirement_result, not in the current lists):\n  " + "\n  ".join(missing),
        )

    def test_registered_queue_records_never_claim_a_registered_route(self) -> None:
        # The queue never authorises a route. Only the code registry may say REGISTERED.
        for flow in _queue()["flows"]:
            for key in ("registration_state", "registration_status", "production_registration"):
                if key in flow:
                    with self.subTest(flow_id=flow["flow_id"], key=key):
                        self.assertEqual(flow[key], "NOT_REGISTERED")


if __name__ == "__main__":
    unittest.main()
