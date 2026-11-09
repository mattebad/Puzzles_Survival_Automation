"""Typed, digest-bound product semantics for representative gameplay flows.

This module is deliberately offline-only.  It validates the durable product
authority and the small contract bindings that consume it; it does not select
flows, register runners, or authorize runtime input.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from .profile import ACTIVE_RUNTIME_PROFILE_ID


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHORITY_PATH = REPO_ROOT / "tasks" / "flow_delivery_product_policy.json"
DEFAULT_POLICY_PATH = DEFAULT_AUTHORITY_PATH
AUTHORITY_SCHEMA_VERSION = 2
AUTHORITY_REGISTRY_KIND = "flow_delivery_product_policy"
AUTHORITY_REVISION = "flow-delivery-product-authority-v2-r24"
PRODUCT_AUTHORITY_SCHEMA_VERSION = AUTHORITY_SCHEMA_VERSION
PRODUCT_AUTHORITY_REVISION = AUTHORITY_REVISION
PRODUCT_RECORDS_FIELD = "product_records"
CONTRACT_BINDING_FIELD = "product_authority_binding"
BLUESTACKS_PLATFORM = "bluestacks"
BLUESTACKS_PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
BLUESTACKS_PACKAGE_ID = "com.global.ztmslg"
KNOWN_BLUESTACKS_BINDING_IDS = frozenset(
    {
        "BLUESTACKS_NATIVE_RUNTIME_PROFILE_DIGEST",
        "HOME_NAVIGATION_PRIMITIVES_DIGEST",
        BLUESTACKS_PROFILE_ID,
        BLUESTACKS_PACKAGE_ID,
    }
)
EXPECTED_BLUESTACKS_BINDING_IDS = KNOWN_BLUESTACKS_BINDING_IDS
HOME_AUTHORITIES = frozenset({"HOME_READY", "HOME_LOCALIZED", "HOME_CANONICAL"})
RECORD_TYPES = frozenset(
    {
        "resource_item",
        "enhancement_family",
        "supply_depot",
        "aggregate_daily_claim",
        "activity_milestone_claim",
        "nova_praise",
        "ultimate_challenge",
        "bioenhancer_research",
        "noahs_tavern_recruitment",
        "campaign_ap",
        "troop_training",
        "gathering_resources",
        "zombie_lair",
        "ruins_shop_purchase",
        "ruins_challenge",
        "alliance_help",
        "rare_earth_shop_purchase",
        "alliance_shop_purchase",
        "alliance_donation",
        "daily_shops_purchase",
        "hero_upgrade",
        "hero_duel",
        "recommended_research",
        "food_farm_output_boost",
        "hall_of_war_zombie_zero",
        "nanoweapon_normal_craft",
        "nano_material_production",
        "vip_points_popup_dismissal",
        "world_map_navigation",
    }
)
RECORD_IDS = frozenset(
    {
        "use_resource_item",
        "enhancement_family",
        "supply_depot",
        "aggregate_daily_claim",
        "activity_milestone_claim",
        "nova_praise",
        "ultimate_challenge",
        "bioenhancer_research",
        "noahs_tavern_recruitment",
        "campaign_ap",
        "troop_training",
        "gathering_resources",
        "zombie_lair",
        "ruins_shop_purchase",
        "ruins_challenge",
        "alliance_help",
        "rare_earth_shop_purchase",
        "alliance_shop_purchase",
        "alliance_donation",
        "daily_shops_purchase",
        "hero_upgrade",
        "hero_duel",
        "recommended_research",
        "food_farm_output_boost",
        "hall_of_war_zombie_zero",
        "nanoweapon_normal_craft",
        "nano_material_production",
        "vip_points_popup_dismissal",
        "world_map_navigation",
    }
)
PRODUCT_RECORD_IDS = RECORD_IDS
POLICY_STATUSES = frozenset(
    {
        "explicitly_approved",
        "navigation_only_validation",
        "supervised_consequential_validation",
        "unresolved_user_decision",
        "prohibited",
    }
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DAILY_RESET_POLICY_ID = "daily-reset-static-utc-midnight"
DAILY_RESET_POLICY_SCOPE = "global.daily_reset"
DAILY_RESET_POLICY_STATUS = "explicitly_approved"
DAILY_RESET_POLICY_TIMEZONE = "UTC"
DAILY_RESET_POLICY_RESET_TIME = "00:00:00"
DAILY_RESET_POLICY_INTERVAL_SECONDS = 86400
DAILY_RESET_POLICY_SOURCE = "explicit_user_direction_2026-08-20"
DAILY_RESET_POLICY_DECISION = (
    "Daily reset is exactly 00:00:00 UTC every 86400 seconds."
)
DAILY_RESET_POLICY_EXPECTED = {
    "policy_id": DAILY_RESET_POLICY_ID,
    "scope": DAILY_RESET_POLICY_SCOPE,
    "status": DAILY_RESET_POLICY_STATUS,
    "decision": DAILY_RESET_POLICY_DECISION,
    "timezone": DAILY_RESET_POLICY_TIMEZONE,
    "reset_time": DAILY_RESET_POLICY_RESET_TIME,
    "interval_seconds": DAILY_RESET_POLICY_INTERVAL_SECONDS,
    "source": DAILY_RESET_POLICY_SOURCE,
}

# Product authority must not absorb implementation, runtime, or orchestration
# domains.  These are field names rather than words in semantic descriptions.
FORBIDDEN_RECORD_FIELDS = frozenset(
    {
        "coordinate",
        "coordinates",
        "ocr",
        "ocr_tokens",
        "profile",
        "profile_id",
        "runtime",
        "runtime_binding",
        "runtime_profile",
        "runtime_profile_id",
        "proof",
        "proof_state",
        "status",
        "queue",
        "queue_state",
        "registration",
        "registration_state",
        "scheduler",
        "scheduler_eligibility",
        "conductor",
        "conductor_state",
        "plan",
        "backlog",
        "implementation",
        "implementation_status",
        "platform_binding",
    }
)


class ProductAuthorityError(ValueError):
    """Raised when product authority or a consuming binding is invalid."""


# Compatibility spelling for callers that prefer a validation-specific name.
ProductAuthorityValidationError = ProductAuthorityError


def canonical_json_bytes(payload: Any) -> bytes:
    """Return the deterministic JSON byte representation used for digests."""

    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductAuthorityError("payload is not canonically JSON serializable") from exc


def canonical_digest(
    payload: Mapping[str, Any],
    *,
    exclude_field: str | None = None,
    digest_field: str | None = None,
) -> str:
    """Hash canonical JSON, excluding the payload's own digest field.

    ``digest_field`` is accepted as a descriptive alias for callers that use
    the authority terminology.  A plain ``digest`` field is excluded by
    default; authority and record callers pass their explicit field names.
    """

    if exclude_field is not None and digest_field is not None:
        raise ProductAuthorityError("specify only one digest exclusion field")
    field = digest_field if digest_field is not None else exclude_field
    if field is None and "digest" in payload:
        field = "digest"
    candidate: Mapping[str, Any] = payload
    if field is not None:
        candidate = deepcopy(dict(payload))
        candidate.pop(field, None)
    return hashlib.sha256(canonical_json_bytes(candidate)).hexdigest()


compute_digest = canonical_digest


def authority_digest(payload: Mapping[str, Any]) -> str:
    """Compute the v2 authority digest without ``authority_digest``."""

    return canonical_digest(payload, exclude_field="authority_digest")


def record_digest(record: Mapping[str, Any]) -> str:
    """Compute a representative record digest without ``record_digest``."""

    return canonical_digest(record, exclude_field="record_digest")


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductAuthorityError(f"{field} must be a non-empty string")
    return value


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ProductAuthorityError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_string_list(value: Any, field: str, *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ProductAuthorityError(f"{field} must be a {'non-empty ' if nonempty else ''}list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ProductAuthorityError(f"{field} must contain non-empty strings")
    return list(value)


def _normalized_field(field: Any) -> str:
    return str(field).strip().casefold().replace("-", "_").replace(" ", "_")


def _walk_record_fields(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _normalized_field(key)
            if normalized in FORBIDDEN_RECORD_FIELDS:
                location = f"{path}.{key}" if path else str(key)
                raise ProductAuthorityError(
                    f"product record contains forbidden authority field: {location}"
                )
            child_path = f"{path}.{key}" if path else str(key)
            _walk_record_fields(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_record_fields(child, f"{path}[{index}]")


def _validate_authority_references(value: Any, field: str) -> None:
    if not isinstance(value, list) or not value:
        raise ProductAuthorityError(f"{field} must contain immutable references")
    kinds: set[str] = set()
    for index, reference in enumerate(value):
        if not isinstance(reference, Mapping):
            raise ProductAuthorityError(f"{field}[{index}] must be an object")
        for required in ("reference_id", "reference_kind", "immutable"):
            if required not in reference:
                raise ProductAuthorityError(f"{field}[{index}] missing {required}")
        _require_nonempty_string(reference["reference_id"], f"{field}[{index}].reference_id")
        kind = _require_nonempty_string(
            reference["reference_kind"], f"{field}[{index}].reference_kind"
        )
        if kind not in {"user_direction", "native_authority"}:
            raise ProductAuthorityError(
                f"{field}[{index}].reference_kind must be user_direction or native_authority"
            )
        if reference["immutable"] is not True:
            raise ProductAuthorityError(f"{field}[{index}] must be immutable")
        kinds.add(kind)
    if kinds != {"user_direction", "native_authority"}:
        raise ProductAuthorityError(
            f"{field} must include both user_direction and native_authority references"
        )

def _validate_home_route(record: Mapping[str, Any], record_type: str) -> None:
    route = record.get("semantic_entry_route")
    if not isinstance(route, Mapping):
        raise ProductAuthorityError("semantic_entry_route must be an object")
    sources = route.get("source_home_authorities")
    _require_string_list(sources, "semantic_entry_route.source_home_authorities")
    if any(source not in HOME_AUTHORITIES for source in sources):
        raise ProductAuthorityError("semantic entry route contains an untyped Home authority")
    target = _require_nonempty_string(route.get("target"), "semantic_entry_route.target")
    expected_target = {
        "resource_item": "BAG",
        "enhancement_family": "COMMANDER",
        "supply_depot": "SUPPLY_DEPOT",
        "aggregate_daily_claim": "DAILY",
        "activity_milestone_claim": "QUEST",
        "nova_praise": "RESEARCH_LAB",
        "ultimate_challenge": "CAMPAIGN",
        "bioenhancer_research": "RESEARCH_LAB",
        "noahs_tavern_recruitment": "NOAHS_TAVERN",
        "campaign_ap": "CAMPAIGN",
        "troop_training": "TRAINING_FACILITIES",
        "gathering_resources": "WORLD",
        "zombie_lair": "ZOMBIE_LAIR",
        "ruins_shop_purchase": "RUINS_SHOP",
        "ruins_challenge": "RUINS",
        "alliance_help": "ALLIANCE",
        "rare_earth_shop_purchase": "RARE_EARTH_SHOP",
        "alliance_donation": "ALLIANCE_TECH",
        "daily_shops_purchase": "RUINS_SHOP",
        "alliance_shop_purchase": "ALLIANCE_SHOP",
        "hero_upgrade": "HERO",
        "hero_duel": "HERO_DUEL",
        "recommended_research": "RESEARCH_CENTER",
        "food_farm_output_boost": "FOOD_FARM",
        "hall_of_war_zombie_zero": "HALL_OF_WAR",
        "nanoweapon_normal_craft": "NANOWEAPON",
        "nano_material_production": "NANOWEAPON",
        "world_map_navigation": "WORLD",
        "vip_points_popup_dismissal": "HOME",
    }
    expected_target = expected_target[record_type]
    if target != expected_target:
        raise ProductAuthorityError(
            f"{record_type} semantic entry route must target {expected_target}"
        )


def _validate_common_record(record: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(record, Mapping):
        raise ProductAuthorityError("product record must be an object")
    _walk_record_fields(record)
    record_id = _require_nonempty_string(record.get("record_id"), "record_id")
    record_type = _require_nonempty_string(record.get("record_type"), "record_type")
    if record_id not in RECORD_IDS or record_type not in RECORD_TYPES:
        raise ProductAuthorityError("unknown typed product record")
    expected_type = {
        "use_resource_item": "resource_item",
        "enhancement_family": "enhancement_family",
        "supply_depot": "supply_depot",
        "aggregate_daily_claim": "aggregate_daily_claim",
        "activity_milestone_claim": "activity_milestone_claim",
        "nova_praise": "nova_praise",
        "ultimate_challenge": "ultimate_challenge",
        "bioenhancer_research": "bioenhancer_research",
        "noahs_tavern_recruitment": "noahs_tavern_recruitment",
        "campaign_ap": "campaign_ap",
        "troop_training": "troop_training",
        "gathering_resources": "gathering_resources",
        "zombie_lair": "zombie_lair",
        "ruins_shop_purchase": "ruins_shop_purchase",
        "ruins_challenge": "ruins_challenge",
        "alliance_help": "alliance_help",
        "rare_earth_shop_purchase": "rare_earth_shop_purchase",
        "alliance_shop_purchase": "alliance_shop_purchase",
        "alliance_donation": "alliance_donation",
        "daily_shops_purchase": "daily_shops_purchase",
        "hero_upgrade": "hero_upgrade",
        "hero_duel": "hero_duel",
        "recommended_research": "recommended_research",
        "food_farm_output_boost": "food_farm_output_boost",
        "hall_of_war_zombie_zero": "hall_of_war_zombie_zero",
        "nanoweapon_normal_craft": "nanoweapon_normal_craft",
        "nano_material_production": "nano_material_production",
        "world_map_navigation": "world_map_navigation",
        "vip_points_popup_dismissal": "vip_points_popup_dismissal",
    }
    if record_type != expected_type[record_id]:
        raise ProductAuthorityError("product record id/type discriminator mismatch")
    for field in (
        "purpose",
        "recurrence",
        "objective",
        "action",
        "semantic_effect",
        "terminal_requirement",
        "daily_ownership",
        "record_revision",
    ):
        if field not in record:
            raise ProductAuthorityError(f"product record missing {field}")
    _require_nonempty_string(record["purpose"], "purpose")
    _require_nonempty_string(record["recurrence"], "recurrence")
    _require_nonempty_string(record["objective"], "objective")
    _require_nonempty_string(record["action"], "action")
    _require_nonempty_string(record["record_revision"], "record_revision")
    if not isinstance(record["semantic_effect"], Mapping):
        raise ProductAuthorityError("semantic_effect must be an object")
    if not isinstance(record["terminal_requirement"], Mapping):
        raise ProductAuthorityError("terminal_requirement must be an object")
    if record["terminal_requirement"].get("home_authority") != "HOME_CANONICAL":
        raise ProductAuthorityError("terminal requirement must use HOME_CANONICAL")
    if not isinstance(record["daily_ownership"], Mapping):
        raise ProductAuthorityError("daily_ownership must be an object")
    selected_daily = record["daily_ownership"].get("selected_daily_prerequisite")
    if record_type == "aggregate_daily_claim":
        if selected_daily is not True:
            raise ProductAuthorityError(
                "aggregate Daily Claim record must require selected-Daily ownership"
            )
    elif selected_daily is not False:
        raise ProductAuthorityError(
            "direct product record must not require a selected-Daily prerequisite"
        )
    elif record_type not in {"noahs_tavern_recruitment", "zombie_lair"} and (
        record["daily_ownership"].get("daily_owner") is not None
        or record["daily_ownership"].get("point_credit_trigger") is not None
    ):
        raise ProductAuthorityError(
            "direct product record must not own Daily or claim point credit"
        )

    _validate_home_route(record, record_type)
    _validate_authority_references(record.get("authority_references"), "authority_references")
    _require_sha256(record.get("record_digest"), "record_digest")
    if record["record_digest"] != record_digest(record):
        raise ProductAuthorityError(f"stale record digest for {record_id}")
    return record_id, record_type


def _validate_resource_record(record: Mapping[str, Any]) -> None:
    if record["objective"] != "use_resource_item":
        raise ProductAuthorityError("resource record objective must be use_resource_item")
    target = record.get("target")
    if not isinstance(target, Mapping):
        raise ProductAuthorityError("resource record target must be an object")
    if (
        target.get("item_name") != "1K Food"
        or target.get("variant") != "1K Food"
        or target.get("owned") is not True
    ):
        raise ProductAuthorityError("resource record must target exactly one owned 1K Food")
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping):
        raise ProductAuthorityError("resource record quantity_cost must be an object")
    if quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError("resource record quantity must be exactly one")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping):
        raise ProductAuthorityError("resource record cost must be an object")
    if (
        cost.get("kind") != "owned_inventory_item"
        or cost.get("amount") != 1
        or cost.get("unit") != "1K Food"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError(
            "resource record must represent the owned 1K Food cost honestly"
        )
    effect = record["semantic_effect"]
    if (
        effect.get("effect_ordinal") != 1
        or effect.get("owned_inventory_delta") != -1
        or effect.get("resource_delta_is_not_a_substitute") is not True
    ):
        raise ProductAuthorityError(
            "resource record must require the exact owned-item decrement of one"
        )
    if effect.get("food_balance_ocr_required") is not False:
        raise ProductAuthorityError(
            "resource record must not require Food-balance OCR"
        )
    if (
        effect.get("last_item_one_to_zero_included") is not True
        or effect.get("consumed_item_identity_bound_to_pre_use_observation") is not True
        or effect.get("zero_after_requires_attributable_last_item_consumption_successor")
        is not True
    ):
        raise ProductAuthorityError(
            "resource record must include the attributable last-item 1-to-0 decrement"
        )
    if record["terminal_requirement"].get("return_required") is not True:
        raise ProductAuthorityError(
            "resource record must require a canonical Home return"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    if "daily navigation" not in forbidden_lower or "selected-daily" not in forbidden_lower:
        raise ProductAuthorityError(
            "resource record must forbid Daily navigation and selected-Daily prerequisites"
        )
    if "unattributed item disappearance" not in forbidden_lower:
        raise ProductAuthorityError(
            "resource record must forbid unattributed item disappearance as consumption"
        )


def _validate_enhancement_record(record: Mapping[str, Any]) -> None:
    if record["objective"] != "enhance_one_exact_variant":
        raise ProductAuthorityError(
            "enhancement record objective must be enhance_one_exact_variant"
        )
    target = record.get("target")
    if not isinstance(target, Mapping):
        raise ProductAuthorityError("enhancement record target must be an object")
    if target.get("variants") != ["Gear", "Chip", "Module"] or target.get(
        "independent"
    ) is not True:
        raise ProductAuthorityError(
            "enhancement record must define independent Gear, Chip, and Module variants"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError("enhancement record quantity must be exactly one")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "owned_inventory_material"
        or cost.get("amount") != 1
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError("enhancement record must use one owned material")
    actions = record.get("actions")
    if not isinstance(actions, list) or len(actions) != 2:
        raise ProductAuthorityError(
            "enhancement record must separate Use and consuming Confirm actions"
        )
    action_by_id = {
        item.get("action_id"): item for item in actions if isinstance(item, Mapping)
    }
    use = action_by_id.get("quantity_selection_use")
    confirm = action_by_id.get("consuming_confirm")
    if (
        not isinstance(use, Mapping)
        or use.get("consumes_material") is not False
        or use.get("owns_material_decrement") is not False
        or not isinstance(confirm, Mapping)
        or confirm.get("consumes_material") is not True
        or confirm.get("owns_material_decrement") is not True
    ):
        raise ProductAuthorityError(
            "enhancement Use and consuming Confirm ownership must be explicit"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in ("auto select", "higher-star", "premium", "unknown", "real-money"):
        if marker not in forbidden_lower:
            raise ProductAuthorityError(
                f"enhancement record must forbid {marker} actions"
            )


def _validate_supply_record(record: Mapping[str, Any]) -> None:
    if record["objective"] != "supply_depot_free_only":
        raise ProductAuthorityError(
            "supply record objective must be supply_depot_free_only"
        )
    target = record.get("target")
    if not isinstance(target, Mapping) or target.get("free_control") != "Free":
        raise ProductAuthorityError("supply record must target the Free control")
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping):
        raise ProductAuthorityError("supply record quantity_cost must be an object")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "zero_cost_free_control"
        or cost.get("amount") != 0
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("supply record must be zero-cost Free-only")
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in ("paid", "diamond", "real-money"):
        if marker not in forbidden_lower:
            raise ProductAuthorityError(f"supply record must forbid {marker} controls")
    effect_text = json.dumps(record["semantic_effect"], sort_keys=True).casefold()
    if "daily 5/5" in effect_text or "completion claim" in effect_text:
        raise ProductAuthorityError(
            "supply product semantics must not claim Daily 5/5 completion"
        )


def _validate_aggregate_daily_claim_record(record: Mapping[str, Any]) -> None:
    """Validate one aggregate Claim occurrence for a current ready batch."""

    if record["objective"] != "aggregate_daily_claim":
        raise ProductAuthorityError(
            "aggregate Daily Claim record objective must be aggregate_daily_claim"
        )
    if record["action"] != "claim_current_ready_daily_batch_once":
        raise ProductAuthorityError(
            "aggregate Daily Claim action must claim one current ready batch"
        )
    if record["recurrence"] != "daily_reset_scoped":
        raise ProductAuthorityError(
            "aggregate Daily Claim recurrence must be daily_reset_scoped"
        )
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_READY", "HOME_CANONICAL"] or route.get(
        "route"
    ) != ["DAILY"]:
        raise ProductAuthorityError(
            "aggregate Daily Claim entry route must be Home to Daily"
        )
    target = record.get("target")
    if not isinstance(target, Mapping) or (
        target.get("kind") != "aggregate_daily_claim"
        or target.get("selected_daily") is not True
        or target.get("row_local") is not False
        or target.get("milestone") is not False
        or target.get("control") != "Claim"
        or target.get("current_ready_batch_required") is not True
        or target.get("batch_identity_required") is not True
    ):
        raise ProductAuthorityError(
            "aggregate Daily Claim must bind the current ready-batch Claim control"
        )
    additional = record.get("additional_product_record_bindings")
    if not isinstance(additional, list) or len(additional) != 1:
        raise ProductAuthorityError(
            "aggregate Daily Claim must reuse exactly one shared Activity Milestone record"
        )
    milestone_binding = additional[0]
    if not isinstance(milestone_binding, Mapping) or (
        milestone_binding.get("binding_type") != "typed_product_record"
        or milestone_binding.get("product_record_id") != "activity_milestone_claim"
        or milestone_binding.get("product_record_revision") != "activity_milestone_claim-v2"
    ):
        raise ProductAuthorityError(
            "aggregate Daily Claim must type-link the shared Activity Milestone record"
        )
    _require_sha256(
        milestone_binding.get("product_record_digest"),
        "additional_product_record_bindings[0].product_record_digest",
    )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError(
            "aggregate Daily Claim quantity must be exactly one dispatch per ready batch"
        )
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "zero_cost_claim"
        or cost.get("amount") != 0
        or cost.get("unit") != "Claim"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("aggregate Daily Claim must be free and zero-cost")
    success_trigger = record.get("aggregate_success_trigger")
    if success_trigger != {
        "action": "exact_free_aggregate_claim",
        "successor": "all_ordinary_claim_controls_cleared",
        "source_bounds": [
            "current_frame",
            "current_ready_batch_identity",
            "daily_reset_identity",
        ],
    }:
        raise ProductAuthorityError(
            "aggregate Daily Claim success trigger must bind the exact free action, cleared controls, and sources"
        )
    effect = record["semantic_effect"]
    if (
        effect.get("effect_ordinal") != 1
        or effect.get("at_most_once_per_current_ready_batch_per_pass") is not True
        or effect.get("distinct_later_ready_batch_allowed_same_reset") is not True
        or effect.get("points_observation_optional") is not True
        or effect.get("points_are_diagnostic_or_corroborative_only") is not True
        or effect.get("points_are_not_a_success_gate_or_ownership_grant") is not True
        or effect.get("objective_identity_not_authorization_input") is not True
        or effect.get("daily_objective_row_inventory_required") is not False
        or effect.get("dispatch_is_not_success_proof") is not True
        or "positive_points_delta_required" in effect
        or "aggregate_claim_control_exhaustion_required" in effect
    ):
        raise ProductAuthorityError(
            "aggregate Daily Claim requires batch-scoped dispatch and the optional-points action success trigger"
        )
    if (
        effect.get("ready_chests_independent_of_aggregate_claim_and_residual_ordinary_controls")
        is not True
        or effect.get("complete_zero_claim_control_scan_required") is not False
        or effect.get("all_chests_static_closure_required") is not False
        or effect.get("points_threshold_required") is not False
        or effect.get("d02_prerequisite") is not False
        or effect.get("sent_unknown_aggregate_claim_retains_runtime_stop") is not True
    ):
        raise ProductAuthorityError(
            "aggregate Daily Claim must keep ready chests independent of residual ordinary controls without scan, static-closure, points, or D02 gates"
        )
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") != "aggregate_daily_claim"
        or "point_credit_trigger" in ownership
    ):
        raise ProductAuthorityError(
            "aggregate Daily Claim owns only the action identity and must not own point credit"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in (
        "milestone",
        "non-claimable",
        "cost-bearing",
        "clipped",
        "unknown",
        "contradictory",
        "stale",
        "identical retry",
        "real-money",
        "150-point threshold prerequisite",
        "Daily objective-row inventory",
        "per-objective Daily attribution",
        "D02 prerequisite",
        "complete zero-Claim scan prerequisite",
        "all-chests-static closure prerequisite",
    ):
        if marker.casefold() not in forbidden_lower:
            raise ProductAuthorityError(
                f"aggregate Daily Claim must forbid {marker} controls"
            )


def _validate_activity_milestone_claim_record(record: Mapping[str, Any]) -> None:
    """Validate one reset-bound, zero-cost claim for an exact chest identity."""

    if record["objective"] != "activity_milestone_claim_one_ready_chest":
        raise ProductAuthorityError(
            "Activity Milestone record objective must be activity_milestone_claim_one_ready_chest"
        )
    if record["action"] != "claim_one_activity_milestone_chest":
        raise ProductAuthorityError(
            "Activity Milestone action must be claim_one_activity_milestone_chest"
        )
    if record["recurrence"] != "daily_reset_scoped":
        raise ProductAuthorityError(
            "Activity Milestone recurrence must be daily_reset_scoped"
        )
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["QUEST", "ACTIVITY_MILESTONES"]:
        raise ProductAuthorityError(
            "Activity Milestone entry route must bind canonical Home to Quest and Activity Milestones"
        )
    target = record.get("target")
    if not isinstance(target, Mapping) or (
        target.get("kind") != "activity_milestone_chest"
        or target.get("eligibility") != "one_current_ready_free_milestone_chest_per_action"
        or target.get("panel") != "ACTIVITY_MILESTONES"
        or target.get("control") != "MILESTONE_CHEST"
        or target.get("quantity") != 1
        or target.get("reset_bound") is not True
        or target.get("distinct_chest_identity_required") is not True
        or target.get("one_claim_per_chest_per_reset") is not True
        or target.get("distinct_chests_per_reset_allowed") is not True
        or target.get("fully_visible") is not True
    ):
        raise ProductAuthorityError(
            "Activity Milestone target must bind one current, ready, fully visible chest identity"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError(
            "Activity Milestone quantity must be exactly one chest dispatch"
        )
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "zero_cost_milestone_claim"
        or cost.get("amount") != 0
        or cost.get("unit") != "MILESTONE_CHEST"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError(
            "Activity Milestone must be free and zero-cost"
        )
    effect = record["semantic_effect"]
    if (
        effect.get("effect_ordinal") != 1
        or effect.get("same_milestone_successor_required") is not True
        or effect.get("same_chest_identity_and_reset_bound") is not True
        or effect.get("positive_bound_points_successor_allowed") is not False
        or effect.get("dispatch_is_not_success_proof") is not True
        or effect.get("success_requires")
        != "same_chest_milestone_state_transition_ready_to_claimed_opened_or_removed"
        or effect.get("terminal_home_separate") is not True
        or effect.get("identical_retry") is not False
    ):
        raise ProductAuthorityError(
            "Activity Milestone must require a same-chest state transition, separate terminal proof, and retry denial"
        )
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError(
            "Activity Milestone must not own ordinary Daily Claim or point credit"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Activity Milestone terminal requirement must return to canonical Home"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in (
        "not-ready",
        "already-claimed",
        "clipped",
        "cost-bearing",
        "unknown",
        "contradictory",
        "stale",
        "ordinary claim",
        "real-money",
        "identical retry",
        "points-only successor",
    ):
        if marker not in forbidden_lower:
            raise ProductAuthorityError(
                f"Activity Milestone must forbid {marker} controls"
            )


def _validate_nova_praise_record(record: Mapping[str, Any]) -> None:
    """Validate one supervised, zero-cost Nova Praise pulse."""

    if record["objective"] != "nova_praise_one_free_pulse":
        raise ProductAuthorityError(
            "Nova Praise record objective must be nova_praise_one_free_pulse"
        )
    if record["action"] != "dispatch_one_free_praise":
        raise ProductAuthorityError(
            "Nova Praise action must be dispatch_one_free_praise"
        )
    if record["recurrence"] != "cooldown_pulse":
        raise ProductAuthorityError("Nova Praise recurrence must be cooldown_pulse")
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != [
        "HOME_READY",
        "HOME_LOCALIZED",
        "HOME_CANONICAL",
    ] or route.get("route") != ["RESEARCH_LAB", "NOVA_LAB"]:
        raise ProductAuthorityError(
            "Nova Praise entry route must bind Home to Research Lab and Nova Lab"
        )
    target = record.get("target")
    if not isinstance(target, Mapping) or (
        target.get("kind") != "nova_praise"
        or target.get("eligibility") != "one_free_attempt_available"
        or target.get("control") != "Praise"
        or target.get("quantity") != 1
    ):
        raise ProductAuthorityError(
            "Nova Praise target must require one currently eligible free Praise"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError("Nova Praise quantity must be exactly one")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "zero_cost_praise"
        or cost.get("amount") != 0
        or cost.get("unit") != "Praise"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("Nova Praise must be free and zero-cost")
    effect = record["semantic_effect"]
    if (
        effect.get("effect_ordinal") != 1
        or effect.get("attempts_before") != "X"
        or effect.get("attempts_after") != "X-1"
        or effect.get("cooldown_seconds") != 300
        or effect.get("cooldown_policy")
        != "fixed_300_seconds_after_capture_delay"
        or effect.get("paid_fallback") is not False
        or effect.get("identical_retry") is not False
        or effect.get("dispatch_is_not_success_proof") is not True
        or effect.get("success_requires")
        != "attempt_decrement_and_cooldown_successor"
    ):
        raise ProductAuthorityError(
            "Nova Praise must type attempts X to X-1, fixed 300-second cooldown, successor proof, and retry/cost boundaries"
        )
    if record["daily_ownership"].get("daily_owner") is not None or record[
        "daily_ownership"
    ].get("point_credit_trigger") is not None or record["daily_ownership"].get(
        "selected_daily_prerequisite"
    ) is not False:
        raise ProductAuthorityError("Nova Praise must not own selected Daily")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Nova Praise terminal requirement must return to canonical Home"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in (
        "paid fallback",
        "premium",
        "unknown",
        "contradictory",
        "identical retry",
        "real-money",
    ):
        if marker not in forbidden_lower:
            raise ProductAuthorityError(f"Nova Praise must forbid {marker} actions")


def _validate_ultimate_challenge_record(record: Mapping[str, Any]) -> None:
    """Validate one reset-bound, zero-cost Ultimate Challenge Flee."""

    if record["objective"] != "ultimate_challenge_one_free_flee":
        raise ProductAuthorityError(
            "Ultimate Challenge record objective must be ultimate_challenge_one_free_flee"
        )
    if record["action"] != "complete_one_free_ultimate_flee":
        raise ProductAuthorityError(
            "Ultimate Challenge action must be complete_one_free_ultimate_flee"
        )
    if record["recurrence"] != "daily_reset_scoped":
        raise ProductAuthorityError(
            "Ultimate Challenge recurrence must be daily_reset_scoped"
        )
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["CAMPAIGN", "ULTIMATE_CHALLENGE"]:
        raise ProductAuthorityError(
            "Ultimate Challenge entry route must bind canonical Home to Campaign and Ultimate Challenge"
        )
    target = record.get("target")
    if not isinstance(target, Mapping) or (
        target.get("kind") != "ultimate_challenge"
        or target.get("eligibility") != "once_per_verified_reset"
        or target.get("control") != "Flee"
        or target.get("quantity") != 1
        or target.get("reset_bound") is not True
    ):
        raise ProductAuthorityError(
            "Ultimate Challenge target must bind one reset-eligible Flee"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError("Ultimate Challenge quantity must be exactly one")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "zero_cost_ultimate_flee"
        or cost.get("amount") != 0
        or cost.get("unit") != "Flee"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("Ultimate Challenge must be free and zero-cost")
    effect = record["semantic_effect"]
    if (
        effect.get("effect_ordinal") != 1
        or effect.get("flee_ceiling") != 1
        or effect.get("resource_delta") != 0
        or effect.get("resource_delta_is_zero") is not True
        or effect.get("dispatch_is_not_success_proof") is not True
        or effect.get("success_requires") != "verified_flee_successor"
        or effect.get("terminal_home_separate") is not True
        or effect.get("identical_retry") is not False
        or effect.get("repeated_flee") is not False
    ):
        raise ProductAuthorityError(
            "Ultimate Challenge must type one Flee, zero resource cost, semantic successor, terminal separation, and retry boundaries"
        )
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError("Ultimate Challenge must not own selected Daily")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Ultimate Challenge terminal requirement must return to canonical Home"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in (
        "auto battle",
        "second flee",
        "repeated flee",
        "campaign ap",
        "ap spend",
        "stamina spend",
        "currency spend",
        "item spend",
        "unknown",
        "identical retry",
        "real-money",
    ):
        if marker not in forbidden_lower:
            raise ProductAuthorityError(
                f"Ultimate Challenge must forbid {marker} actions"
            )


def _validate_noahs_tavern_recruitment_record(record: Mapping[str, Any]) -> None:
    """Validate the split Daily/maintenance free-recruitment authority."""

    if record["objective"] != "noahs_tavern_recruitment":
        raise ProductAuthorityError(
            "Recruitment record objective must be noahs_tavern_recruitment"
        )
    if record["action"] != "dispatch_one_free_recruitment_single":
        raise ProductAuthorityError(
            "Recruitment action must be dispatch_one_free_recruitment_single"
        )
    if record["recurrence"] != "daily_reset_and_independent_cooldown_pulse":
        raise ProductAuthorityError(
            "Recruitment recurrence must bind reset and independent cooldown pulses"
        )
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != [
        "HOME_READY",
        "HOME_LOCALIZED",
        "HOME_CANONICAL",
    ] or route.get("route") != ["NOAHS_TAVERN"]:
        raise ProductAuthorityError(
            "Recruitment entry route must bind Home to Noah's Tavern"
        )
    target = record.get("target")
    tiers = target.get("tiers") if isinstance(target, Mapping) else None
    expected_tiers = {
        "basic": {
            "free_attempts_per_reset": 5,
            "cooldown_seconds": 600,
            "owns_daily_completion": True,
        },
        "intermediate": {
            "free_attempts_per_window": 1,
            "cooldown_seconds": 86400,
            "owns_daily_completion": False,
        },
        "advanced": {
            "free_attempts_per_window": 1,
            "cooldown_seconds": 172800,
            "owns_daily_completion": False,
        },
    }
    if not isinstance(target, Mapping) or (
        target.get("kind") != "noahs_tavern_recruitment"
        or target.get("eligibility") != "one_current_tier_free_single_available"
        or target.get("control") != "Free single"
        or target.get("quantity") != 1
        or target.get("tier_selection_required") is not True
        or tiers != expected_tiers
    ):
        raise ProductAuthorityError(
            "Recruitment target must bind one current tier's free single"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError("Recruitment quantity must be exactly one")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "zero_cost_free_recruitment_single"
        or cost.get("amount") != 0
        or cost.get("unit") != "Free single"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("Recruitment must be free and zero-cost")
    effect = record["semantic_effect"]
    if (
        effect.get("effect_ordinal") != 1
        or effect.get("basic_daily_ceiling") != 5
        or effect.get("basic_cooldown_seconds") != 600
        or effect.get("intermediate_cooldown_seconds") != 86400
        or effect.get("advanced_cooldown_seconds") != 172800
        or effect.get("reset_bound_basic_progress") is not True
        or effect.get("independent_tier_cooldowns") is not True
        or effect.get("tier_state_persisted") is not True
        or effect.get("current_tier_successor_required") is not True
        or effect.get("dispatch_is_not_success_proof") is not True
        or effect.get("success_requires")
        != "positive_same_tier_recruit_result_and_free_attempt_successor"
        or effect.get("paid_fallback") is not False
        or effect.get("premium_fallback") is not False
        or effect.get("item_backed_fallback") is not False
        or effect.get("ten_x_fallback") is not False
        or effect.get("identical_retry") is not False
        or effect.get("basic_owns_daily_completion") is not True
        or effect.get("intermediate_owns_daily_completion") is not False
        or effect.get("advanced_owns_daily_completion") is not False
    ):
        raise ProductAuthorityError(
            "Recruitment must type Basic five/reset, independent tier cooldowns, successor proof, and ownership boundaries"
        )
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") != "five_basic_free_singles_per_reset"
        or ownership.get("point_credit_trigger")
        != "five_basic_recruit_successors"
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError(
            "Recruitment must assign Daily completion only to Basic five"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Recruitment terminal requirement must return to canonical Home"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in (
        "paid",
        "premium",
        "item-backed",
        "10x",
        "ambiguous",
        "unknown",
        "contradictory",
        "stale",
        "identical retry",
        "real-money",
        "intermediate Daily",
        "advanced Daily",
    ):
        if marker.casefold() not in forbidden_lower:
            raise ProductAuthorityError(
                f"Recruitment must forbid {marker} actions"
            )


def _validate_troop_training_record(record: Mapping[str, Any]) -> None:
    """Validate four independently configured queue/slot training variants."""

    if record["objective"] != "troop_training_queue_or_daily_pass":
        raise ProductAuthorityError(
            "Troop Training record objective must be troop_training_queue_or_daily_pass"
        )
    if record["action"] != "dispatch_one_configured_troop_training_action":
        raise ProductAuthorityError(
            "Troop Training action must be dispatch_one_configured_troop_training_action"
        )
    if record["recurrence"] != "queue_slot_and_daily_reset":
        raise ProductAuthorityError(
            "Troop Training recurrence must be queue_slot_and_daily_reset"
        )
    if record.get("record_revision") != "troop_training-v3":
        raise ProductAuthorityError("Troop Training record revision must be troop_training-v3")
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["TRAINING_FACILITIES"]:
        raise ProductAuthorityError(
            "Troop Training entry route must bind canonical Home to Training facilities"
        )
    target = record.get("target")
    expected_variants = {
        "fighter": {
            "enabled": True,
            "target_tier": 8,
            "quantity_mode": "current_max",
            "training_policy": "continuous",
            "allow_resource_boxes": True,
        },
        "vehicle": {
            "enabled": True,
            "target_tier": 1,
            "quantity_mode": "current_max",
            "training_policy": "continuous",
            "allow_resource_boxes": True,
        },
        "shooter": {
            "enabled": True,
            "target_tier": 8,
            "quantity": 250,
            "quantity_mode": "fixed",
            "training_policy": "once_daily",
            "allow_resource_boxes": False,
        },
        "rider": {
            "enabled": True,
            "target_tier": 1,
            "quantity": 250,
            "quantity_mode": "fixed",
            "training_policy": "once_daily",
            "allow_resource_boxes": False,
        },
    }
    if not isinstance(target, Mapping) or target.get("kind") != "troop_training":
        raise ProductAuthorityError("Troop Training target kind is incomplete")
    if target.get("facility_entry") != "one_canonical_home_atlas_training_route":
        raise ProductAuthorityError("Troop Training target must use one canonical facility route")
    if target.get("per_type_contract") != expected_variants:
        raise ProductAuthorityError(
            "Troop Training target must preserve exact four-type configuration"
        )
    if target.get("known_resources") != ["food", "wood", "steel", "gas"]:
        raise ProductAuthorityError("Troop Training target must bind known base resources")
    if target.get("current_max_quantity_source") != "fresh_current_frame_numeric_maximum" or target.get(
        "current_max_fixed_fallback"
    ) is not None:
        raise ProductAuthorityError(
            "Troop Training current_max must use the fresh numeric maximum without a fixed fallback"
        )
    if target.get("commander_talent_requirement") != {
        "policy_id": "commander-talent-preset-helper",
        "required_preset": "Training",
        "verification_before_each_start": True,
        "switch_cost_allowance": "explicitly_observed_zero_cost_only",
        "route_approval_required": True,
    }:
        raise ProductAuthorityError("Troop Training must verify the saved Training preset")
    if target.get("resource_box_continuation") != {
        "allowed_types": ["fighter", "vehicle"],
        "requires_exact_type_tier_and_quantity_match": True,
        "requires_current_recognized_resource_box_popup": True,
        "requires_observed_shortage_and_sufficient_post_box_balances": True,
        "warehouse_only_rejected": True,
        "effect_authority_required_before_consumption": True,
        "shooter_or_rider_allowed": False,
    }:
        raise ProductAuthorityError("Troop Training resource boxes must stay on the exact approved continuation")
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get(
        "quantity"
    ) != "per_type_configured":
        raise ProductAuthorityError(
            "Troop Training quantity must remain per-type configured"
        )
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "known_base_resources"
        or cost.get("amount") != "per_type_configured"
        or cost.get("unit") != "Food/Wood/Steel/Gas"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError(
            "Troop Training must bind configured known-resource cost"
        )
    effect = record["semantic_effect"]
    required_effects = {
        "effect_ordinal": 1,
        "queue_slot_effect": True,
        "active_queue_successor_required": True,
        "positive_timer_spatial_association_required": True,
        "current_max_numeric_reconciliation_required": True,
        "fixed_quantity_exact_required": True,
        "known_resources_required": True,
        "resource_box_policy_bound": True,
        "once_daily_reset_identity_bound": True,
        "current_max_numeric_value_must_be_observed_each_start": True,
        "historical_numeric_maxima_are_not_policy": True,
        "commander_talent_preset_verified_before_start": True,
        "resource_box_continuation_requires_exact_configured_branch": True,
        "resource_box_consumption_requires_effect_authority": True,
        "continuous_policy_repeats_when_slot_available": True,
        "dispatch_is_not_success_proof": True,
        "identical_retry": False,
    }
    if any(effect.get(key) != value for key, value in required_effects.items()):
        raise ProductAuthorityError(
            "Troop Training must require queue/timer successor and exact quantity policy"
        )
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError(
            "Troop Training must not own selected Daily or point credit"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Troop Training terminal requirement must return to canonical Home"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in (
        "train now",
        "premium",
        "speedup",
        "cash mall",
        "shooter or rider resource boxes",
        "unknown tier",
        "unknown quantity",
        "unknown resource",
        "identical retry",
        "real-money",
    ):
        if marker not in forbidden_lower:
            raise ProductAuthorityError(f"Troop Training must forbid {marker} actions")


def _validate_gathering_resources_record(record: Mapping[str, Any]) -> None:
    """Validate evidence-gated Wood, Steel, and Gas gathering authority."""

    if record["objective"] != "gather_resource_variant":
        raise ProductAuthorityError(
            "Gathering record objective must be gather_resource_variant"
        )
    if record["action"] != "dispatch_one_gathering_march":
        raise ProductAuthorityError(
            "Gathering action must be dispatch_one_gathering_march"
        )
    if record["recurrence"] != "pulse_march_slot_timer":
        raise ProductAuthorityError(
            "Gathering recurrence must be pulse_march_slot_timer"
        )
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_READY"]
        or route.get("route")
        != ["WORLD", "SEARCH", "RESOURCE_CATEGORY", "LEVEL_5_NODE", "MARCH"]
    ):
        raise ProductAuthorityError(
            "Gathering entry route must bind HOME_READY to World Search and level-5 march"
        )
    target = record["target"]
    if (
        target.get("kind") != "gathering_resource_node"
        or target.get("supported_variants") != ["WOOD", "STEEL", "GAS"]
        or target.get("level") != 5
        or target.get("search_control") != "WORLD_SEARCH"
        or target.get("category_control") != "RESOURCE_CATEGORY"
        or target.get("gas_reveal") != "one_bounded_left_swipe"
        or target.get("node_binding") != "current_frame_only"
        or target.get("occupancy") != "free_only"
        or target.get("march_slot") != "one_free_slot"
        or target.get("formation") != "default"
        or target.get("source_daily_row_required") is not False
        or target.get("food_authority") != "forbidden"
    ):
        raise ProductAuthorityError(
            "Gathering target must bind supported free level-5 nodes and one free march slot"
        )
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "no_resource_or_currency_cost"
        or cost.get("amount") != 0
        or cost.get("unit") != "resource_or_currency"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError(
            "Gathering must bind one free resource-or-currency-cost march"
        )
    effect = record["semantic_effect"]
    required_effects = (
        "requested_variant_identity_required",
        "level_5_node_identity_required",
        "free_occupancy_successor_required",
        "march_identity_successor_required",
        "free_march_slot_required",
        "default_formation_required",
        "outbound_timer_successor_required",
        "return_timer_successor_required",
        "terminal_home_successor_required",
        "resource_progress_successor_required",
        "dispatch_is_not_success_proof",
    )
    if (
        effect.get("effect_ordinal") != 1
        or any(effect.get(field) is not True for field in required_effects)
        or effect.get("daily_progress_ownership")
        != "separate_catalog_reconciliation"
        or effect.get("identical_retry") is not False
    ):
        raise ProductAuthorityError(
            "Gathering successor, reconciliation, or retry safety effect is incomplete"
        )
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError("Gathering must not own Daily progress")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Gathering terminal requirement must return to canonical Home"
        )
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "food",
        "unknown resource",
        "ambiguous resource",
        "level-5",
        "occupied",
        "already-targeted",
        "existing march",
        "free march slot",
        "formation",
        "stale",
        "gas",
        "attack",
        "combat",
        "ambiguous",
        "identical retry",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(
                f"Gathering forbidden actions must include {marker}"
            )
def _validate_hero_duel_record(record: Mapping[str, Any]) -> None:
    """Validate approved three-cycle Hero Duel–Survival product semantics."""

    if record["objective"] != "bounded_hero_duel_participation":
        raise ProductAuthorityError("Hero Duel objective must be bounded participation")
    if record["action"] != "complete_up_to_three_free_hero_duel_cycles":
        raise ProductAuthorityError("Hero Duel action must be the approved free cycle")
    if record["recurrence"] != "daily_reset_scoped":
        raise ProductAuthorityError("Hero Duel recurrence must be daily_reset_scoped")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_CANONICAL"]
        or route.get("target") != "HERO_DUEL"
        or route.get("route") != ["ARENA", "HERO_DUEL_SURVIVAL"]
    ):
        raise ProductAuthorityError(
            "Hero Duel must enter the exact Survival event from canonical Home"
        )
    target = record["target"]
    target_requirements = {
        "kind": "hero_duel",
        "event_identity": "hero_duel_survival",
        "event_variant": "SURVIVAL",
        "event_active_required": True,
        "target_identity": "HERO_DUEL_FREE_CHALLENGE",
        "maximum_cycles_per_reset": 3,
        "maximum_hero_slots": 5,
        "hero_selection": "first_five_eligible_displayed",
        "attack_selection": "first_five_eligible_displayed",
        "excluded_heroes_skipped": True,
        "attack_lineup_independent": True,
        "attack_lineup_fill_missing_only": True,
        "terminal_home": "HOME_CANONICAL",
    }
    if not isinstance(target, Mapping) or any(
        target.get(key) != value for key, value in target_requirements.items()
    ):
        raise ProductAuthorityError("Hero Duel target exceeds or weakens the approved bounds")
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "zero_cost_hero_duel_free_entry"
        or cost.get("amount") != 0
        or cost.get("unit") != "entry"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("Hero Duel entry must be an exact zero-cost Free action")
    effect = record["semantic_effect"]
    required_effects = {
        "maximum_confirmed_cycles_per_reset": 3,
        "event_active_evidence_required": True,
        "survival_event_identity_must_remain_current": True,
        "free_allowance_and_zero_cost_required": True,
        "defense_formation_save_required": True,
        "defense_formation_slots": 5,
        "defense_selection": "first_five_eligible_displayed",
        "attack_selection": "first_five_eligible_displayed",
        "current_event_exclusions_skipped": True,
        "attack_formation_slots": 5,
        "attack_formation_is_independent": True,
        "fill_missing_attack_slots_only": True,
        "preserve_complete_valid_attack_formation": True,
        "battle_loaded_state_required": True,
        "exit_as_soon_as_wave_one_battle_loaded": True,
        "flee_warning_and_flee_control_required": True,
        "fight_allowed": False,
        "loss_result_acceptable": True,
        "result_continue_required": True,
        "positive_participation_successor_required": True,
        "confirmed_cycle_progress_persisted": True,
        "transport_is_not_success_proof": True,
        "pass_balance_decrease_allowed": False,
        "daily_progress_maximum": 3,
        "canonical_home_successor_required": True,
        "daily_ownership": "none",
        "daily_inspection_required": False,
        "points_attribution_required": False,
        "identical_retry": False,
    }
    if any(effect.get(key) != value for key, value in required_effects.items()):
        raise ProductAuthorityError("Hero Duel effect does not match the bounded free cycle")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError("Hero Duel must return to canonical Home")
    forbidden = json.dumps(record["forbidden_actions"], ensure_ascii=False, sort_keys=True).casefold().replace("–", " ")
    for marker in (
        "hero duel glory",
        "paid entry",
        "premium entry",
        "activate",
        "refresh opponent",
        "fight",
        "combat loop",
        "reward farming",
        "unknown event",
        "inactive event",
        "unknown cost",
        "unknown attempts",
        "insufficient attempts",
        "identical retry",
        "real-money",
        "daily inspection",
        "d02",
        "points attribution",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(f"Hero Duel must forbid {marker}")


def _validate_recommended_research_record(record: Mapping[str, Any]) -> None:
    """Validate one first-row Recommended Research start with ordinary resources."""

    if record["objective"] != "start_first_recommended_research":
        raise ProductAuthorityError("Recommended Research objective must use the first row")
    if record["action"] != "start_one_affordable_recommended_research":
        raise ProductAuthorityError("Recommended Research action must be one start")
    if record["recurrence"] != "daily_reset_scoped":
        raise ProductAuthorityError("Recommended Research must be reset-scoped")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_CANONICAL"]
        or route.get("target") != "RESEARCH_CENTER"
        or route.get("route") != ["RESEARCH_CENTER", "RECOMMENDED_RESEARCH"]
    ):
        raise ProductAuthorityError("Recommended Research route must use Research Center")
    target = record["target"]
    target_requirements = {
        "kind": "recommended_research",
        "recommendation_position": 1,
        "recommendation_selection": "first_displayed_row",
        "recommendation_row_control": "ROW_RESEARCH_NAVIGATION",
        "detail_start_control": "DETAIL_RESEARCH_START",
        "row_research_only_navigates": True,
        "queue1_idle_required": True,
        "queue2_activation_allowed": False,
        "all_prerequisites_known_and_met": True,
        "ordinary_resources": ["food", "wood", "steel", "gas"],
        "exact_cost_and_balance_required": True,
        "maximum_starts_per_reset": 1,
        "shortage_behavior": "record_exact_shortages_and_defer",
        "terminal_home": "HOME_CANONICAL",
    }
    if not isinstance(target, Mapping) or any(
        target.get(key) != value for key, value in target_requirements.items()
    ):
        raise ProductAuthorityError(
            "Recommended Research must be first-row, idle, prerequisite, and cost bounded"
        )
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "exact_current_ordinary_resources"
        or cost.get("amount") is not None
        or cost.get("unit") != "FOOD_WOOD_STEEL_GAS"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError(
            "Recommended Research cost must be the exact current ordinary-resource rows"
        )
    effect = record["semantic_effect"]
    required_effects = {
        "maximum_starts_per_reset": 1,
        "first_recommendation_only": True,
        "queue1_idle_before_start": True,
        "all_prerequisites_must_be_current_and_met": True,
        "all_four_ordinary_costs_and_balances_required": True,
        "shortages_recorded_and_deferred": True,
        "recommendation_row_research_navigates_only": True,
        "detail_research_control_starts_action": True,
        "active_queue_successor_for_same_identity_required": True,
        "positive_remaining_timer_required": True,
        "all_four_resource_debits_required": True,
        "dispatch_is_not_success_proof": True,
        "queue2_activation_allowed": False,
        "research_now_diamonds_allowed": False,
        "alternate_technology_allowed": False,
        "daily_ownership": "none",
        "daily_inspection_required": False,
        "points_attribution_required": False,
        "identical_retry": False,
    }
    if any(effect.get(key) != value for key, value in required_effects.items()):
        raise ProductAuthorityError(
            "Recommended Research effect weakens queue, cost, or shortage policy"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError("Recommended Research must return to canonical Home")
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "research now",
        "diamonds",
        "queue 2",
        "activate",
        "box",
        "purchase",
        "refill",
        "alternate technology",
        "technology substitution",
        "gathering",
        "base resource collection",
        "unknown target",
        "unknown prerequisite",
        "unknown cost",
        "insufficient ordinary balance",
        "identical retry",
        "real-money",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(f"Recommended Research must forbid {marker}")


def _validate_food_farm_output_boost_record(record: Mapping[str, Any]) -> None:
    """Validate one reset-scoped Food Farm boost and any prerequisite collection."""

    if record["objective"] != "food_farm_output_boost":
        raise ProductAuthorityError("Food Farm objective must be food_farm_output_boost")
    if record["action"] != "apply_one_food_farm_output_boost":
        raise ProductAuthorityError("Food Farm action must be one boost")
    if record["recurrence"] != "daily_reset_scoped":
        raise ProductAuthorityError("Food Farm boost must be reset-scoped")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_CANONICAL"]
        or route.get("target") != "FOOD_FARM"
        or route.get("route") != ["MAPPED_FOOD_FARM", "BOOST"]
    ):
        raise ProductAuthorityError("Food Farm route must bind a current mapped Farm")
    target = record["target"]
    target_requirements = {
        "kind": "food_farm_output_boost",
        "resource_type": "FOOD",
        "farm_identity": "current_safely_bound_mapped_farm",
        "maximum_boosts_per_reset": 1,
        "owned_item_preferred": True,
        "owned_item_count_must_be_independently_observed": True,
        "item_action_cost": 1,
        "item_action_cost_is_not_inventory_count": True,
        "diamond_fallback_only_when_owned_item_count_is_zero": True,
        "diamond_offer_must_match_current_item_duration_cost_and_balance": True,
        "diamond_fallback_offer": {
            "control": "Boost output (1-day)",
            "duration": "1-day",
            "currency": "DIAMONDS",
            "maximum_authorized_price_diamonds": 48,
            "current_numeric_price_must_be_observed": True,
            "current_numeric_price_must_not_exceed_authorized_cap": True,
            "current_balance_must_cover_exact_observed_price": True,
            "price_and_balance_rechecked_if_confirmation_appears": True,
        },
        "diamond_price_cap_not_assumed_current_price": True,
        "unknown_or_changed_offer_blocks": True,
        "terminal_home": "HOME_CANONICAL",
    }
    if not isinstance(target, Mapping) or any(
        target.get(key) != value for key, value in target_requirements.items()
    ):
        raise ProductAuthorityError("Food Farm target weakens the one-boost policy")
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "owned_item_preferred_or_exact_diamond_offer"
        or cost.get("amount") is not None
        or cost.get("unit") != "food_farm_boost_item_or_diamonds"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError("Food Farm cost must preserve item-first exact fallback")
    effect = record["semantic_effect"]
    required_effects = {
        "maximum_boosts_per_reset": 1,
        "item_preferred_over_diamonds": True,
        "owned_item_identity_count_and_duration_required": True,
        "exact_current_diamond_item_duration_cost_balance_required": True,
        "diamond_price_cap_not_assumed_current_price": True,
        "exact_current_numeric_price_and_balance_required": True,
        "current_price_must_not_exceed_authorized_cap": True,
        "current_price_rechecked_if_confirmation_appears": True,
        "changed_confirmation_prompt_blocks": True,
        "same_farm_active_boost_successor_required": True,
        "positive_boosting_timer_required": True,
        "dispatch_is_not_success_proof": True,
        "first_farm_tap_may_collect_multiple_buildings": True,
        "collection_exact_balance_delta_for_each_resource_required": True,
        "collection_balances_must_be_reconciled_before_boost": True,
        "collection_is_not_boost_success": True,
        "global_food_output_boost_item_allowed": False,
        "daily_progress_maximum": 1,
        "daily_ownership": "none",
        "daily_inspection_required": False,
        "points_attribution_required": False,
        "identical_retry": False,
    }
    if any(effect.get(key) != value for key, value in required_effects.items()):
        raise ProductAuthorityError("Food Farm effect weakens inventory or boost accounting")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError("Food Farm boost must return to canonical Home")
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "buy box",
        "resource building boost",
        "global food output boost",
        "unknown item",
        "ambiguous item",
        "unknown inventory count",
        "inventory count inferred from action cost",
        "unknown duration",
        "unknown diamond price",
        "unknown balance",
        "changed prompt",
        "real-money",
        "second boost",
        "identical retry",
        "daily inspection",
        "d02",
        "points attribution",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(f"Food Farm boost must forbid {marker}")

def _validate_hall_of_war_zombie_zero_record(record: Mapping[str, Any]) -> None:
    """Validate one exact-cost, saved-formation Zombie Zero visit and row claim."""

    if (
        record["objective"] != "hall_of_war_zombie_zero_dispatch_and_reward"
        or record["action"] != "dispatch_once_then_claim_own_ready_daily_reward"
        or record["recurrence"] != "daily_reset_scoped"
    ):
        raise ProductAuthorityError("Hall of War must remain one reset-scoped Zombie Zero visit")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_CANONICAL"]
        or route.get("target") != "HALL_OF_WAR"
        or route.get("route") != ["HALL_OF_WAR", "ZOMBIE_ZERO"]
    ):
        raise ProductAuthorityError("Hall of War must bind the exact Zombie Zero route")
    target = record["target"]
    target_requirements = {
        "kind": "hall_of_war_zombie_zero",
        "page_identity": "ZOMBIE_ZERO",
        "dispatch_page_identity": "ZOMBIE_ZERO_DISPATCH",
        "maximum_dispatches_per_reset": 1,
        "attempt_ordinal": 1,
        "attempt_state_must_be_current": True,
        "attempt_state_values": ["ready", "busy", "unavailable", "unknown"],
        "busy_or_unavailable_no_dispatch": True,
        "attempt_availability_or_cooldown_is_not_hardcoded": True,
        "dispatch_cost_state_values": ["explicit_zero", "nonzero", "unknown"],
        "dispatch_requires_current_explicit_zero_cost": True,
        "unknown_or_nonzero_cost_blocks": True,
        "premium_or_refill_allowed": False,
        "current_troop_loss_effect_must_be_known_and_approved": True,
        "loss_free_behavior_assumed": False,
        "commander_talent_requirement": {
            "policy_id": "commander-talent-preset-helper",
            "required_preset": "Military",
            "verification_before_dispatch": True,
            "switch_policy": "verify_only_without_route_cost_approval",
            "route_approval_required": True,
        },
        "saved_troop_set_identity": "Troop Set 1",
        "saved_troop_set_must_be_selected_and_applied": True,
        "five_heroes_must_be_populated": True,
        "current_troop_capacity_must_be_numeric_and_positive": True,
        "current_troops_must_equal_current_capacity": True,
        "quick_select_allowed": False,
        "formation_edit_allowed": False,
        "positive_result_identity": "HALL_OF_WAR_ZOMBIE_ZERO_HISTORY_HIGH_RESULT",
        "minimum_damage_threshold": None,
        "maximum_reward_claims_per_reset": 1,
        "reward_state_values": ["ready", "unavailable", "claimed", "unknown"],
        "reward_claim_requires_current_glowing_ready_row": True,
        "reward_claim_is_one_daily_row_tap": True,
        "claimed_reward_successor_requires_current_row_checkmarks": True,
        "individual_reward_icon_taps_allowed": False,
        "terminal_home": "HOME_CANONICAL",
    }
    if not isinstance(target, Mapping) or any(
        target.get(key) != value for key, value in target_requirements.items()
    ):
        raise ProductAuthorityError("Hall of War target weakens current attempt, formation, or reward guards")
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "current_explicit_zero_only"
        or cost.get("amount") != 0
        or cost.get("unit") != "resource_or_currency"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("Zombie Zero dispatch must require current observed zero cost")
    effect = record["semantic_effect"]
    required_effects = {
        "maximum_dispatches_per_reset": 1,
        "current_attempt_state_and_ordinal_required": True,
        "busy_or_unavailable_is_no_input": True,
        "daily_attempt_limit_and_cooldown_not_hardcoded": True,
        "exact_current_zero_cost_source_required": True,
        "no_cost_inferred_from_missing_price_label": True,
        "premium_or_changed_confirmation_blocks": True,
        "current_troop_loss_effect_must_be_known_and_approved": True,
        "loss_free_behavior_assumed": False,
        "saved_commander_talent_preset_verified_before_dispatch": True,
        "saved_troop_set_one_must_be_applied": True,
        "five_heroes_and_full_current_troop_capacity_required": True,
        "history_high_result_successor_required": True,
        "minimum_damage_threshold": None,
        "daily_reward_is_a_separate_effect": True,
        "reward_claim_requires_same_reset_positive_participation": True,
        "reward_claim_requires_current_glowing_ready_row": True,
        "one_row_tap_and_current_claimed_checkmark_successor_required": True,
        "reward_claim_is_not_inferred_from_dispatch": True,
        "unavailable_or_claimed_reward_no_input": True,
        "challenge_and_reward_outcomes_reconciled_independently": True,
        "daily_ownership": "none",
        "daily_inspection_required": False,
        "d02_prerequisite": False,
        "points_attribution_required": False,
        "identical_retry": False,
    }
    if not isinstance(effect, Mapping) or any(
        effect.get(key) != value for key, value in required_effects.items()
    ):
        raise ProductAuthorityError("Hall of War effects must independently reconcile result and reward")
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError("Zombie Zero must not claim Daily row ownership or prerequisites")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError("Hall of War must return to canonical Home")

    if record.get("record_revision") != "hall_of_war_zombie_zero-v1":
        raise ProductAuthorityError("Hall of War record revision is not the current product version")
    forbidden = json.dumps(record.get("forbidden_actions", ()), sort_keys=True).casefold()
    for marker in (
        "unknown or nonzero dispatch cost",
        "premium or refill",
        "unapproved troop loss",
        "quick select",
        "troop set 2",
        "troop set 3",
        "share",
        "achievement",
        "individual reward icon",
        "daily objective-row",
        "d02",
        "points attribution",
        "identical retry",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(f"Hall of War must forbid {marker}")

def _validate_hero_upgrade_record(record: Mapping[str, Any]) -> None:
    """Validate bounded Wali semantics separately from runtime route admission."""

    if (
        record["objective"] != "upgrade_hero"
        or record["action"] != "upgrade_wali_individual_normal_batch_with_standard_evolution_support"
        or record["recurrence"] != "daily_reset_scoped"
        or record["record_revision"] != "hero_upgrade-v4"
    ):
        raise ProductAuthorityError("Hero Upgrade must use the approved v4 reset-scoped batch action")
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["HERO"]:
        raise ProductAuthorityError("Hero Upgrade entry route must bind canonical Home to Hero")
    manuals = [
        "COMBAT_MANUAL_I",
        "COMBAT_MANUAL_II",
        "COMBAT_MANUAL_III",
        "COMBAT_MANUAL_IV",
        "COMBAT_MANUAL_V",
    ]
    expected_target = {
        "kind": "hero_upgrade",
        "hero_identity": "Wali",
        "hero_selected": True,
        "current_level": None,
        "evolution_cap": None,
        "next_evolution_cap": None,
        "target_identity": "hero-upgrade",
        "normal_upgrade_material": "ANTISERUM",
        "standard_evolution_materials": ["ANTISERUM", *manuals],
        "normal_single_upgrade": True,
        "normal_upgrade_count_per_reset": 3,
        "evolution_only_at_displayed_cap": True,
        "evolution_level_change_counts_as_normal_upgrade": False,
        "policy_status": "explicitly_approved",
        "upgrade_dispatch_allowed": True,
        "approved_action_kinds": ["HERO_UPGRADE_SINGLE", "HERO_EVOLUTION_STANDARD"],
        "terminal_home": "HOME_CANONICAL",
    }
    if record["target"] != expected_target:
        raise ProductAuthorityError("Hero Upgrade target or standard-material semantics changed")
    blocked_reset_path = {
        "evidence_required": True,
        "operationally_blocked": True,
        "campaign_block_proven": False,
        "final_150_diamond_confirmation_proven": False,
        "reset_action_excluded": True,
    }
    expected_cost = {
        "quantity": 1,
        "normal_upgrade": {
            "action": "individual_single_level_inputs",
            "material": "ANTISERUM",
            "amount": None,
            "current_observation_required": True,
            "maximum_inputs_per_batch": 3,
            "current_quote_before_each_input": True,
            "free_only": False,
        },
        "standard_evolution": {
            "action": "one_standard_evolution",
            "materials": ["ANTISERUM", *manuals],
            "exact_current_vector_required": True,
            "free_only": False,
        },
        "reset_campaign_diamond_path": blocked_reset_path,
    }
    if record["quantity_cost"] != expected_cost:
        raise ProductAuthorityError("Hero Upgrade costs must use current exact standard material evidence")
    expected_effect = {
        "normal_upgrade_count_per_reset": 3,
        "exact_selected_wali_evidence_required": True,
        "stable_level_and_displayed_cap_required": True,
        "exact_current_material_vector_and_balance_required": True,
        "normal_batch_cumulative_level_and_debit_required": True,
        "per_input_settled_successor_required": False,
        "partial_batch_requires_exact_known_prefix": True,
        "exact_antiserum_debit_required": True,
        "evolution_only_at_displayed_cap": True,
        "evolution_automatic_level_not_counted": True,
        "evolution_manual_decrement_numeric_receipt_or_named_usage_toast_required": True,
        "evolution_named_toast_requires_exact_quoted_cost_and_unique_cap_transition": True,
        "evolution_antiserum_debit_required": True,
        "confirmed_normal_count_persists_through_evolution_and_restart": True,
        "daily_progress_successor_required": False,
        "daily_ownership": "none",
        "points_credit_required": False,
        "reset_campaign_diamond_path": blocked_reset_path,
        "upgrade_dispatch_allowed": True,
        "approved_action_kinds": ["HERO_UPGRADE_SINGLE", "HERO_EVOLUTION_STANDARD"],
        "current_explicit_authorization_required": True,
        "canonical_supervised_claim_required": True,
        "native_evidence_required": True,
        "canonical_home_successor_required": True,
        "dispatch_is_not_success_proof": True,
        "identical_retry": False,
    }
    if record["semantic_effect"] != expected_effect:
        raise ProductAuthorityError("Hero Upgrade effect must preserve exact transitions and evidence gates")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError("Hero Upgrade terminal requirement must return to canonical Home")
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError("Hero Upgrade must not depend on Daily, D02, or points")
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "bulk upgrade",
        "normal upgrades above three per reset",
        "counting automatic evolution levels toward the normal-upgrade quota",
        "premium material",
        "premium currency",
        "unknown or ambiguous hero",
        "unknown or ambiguous level",
        "unknown or ambiguous displayed cap",
        "unknown or ambiguous material",
        "unknown or ambiguous cost",
        "insufficient material balance",
        "reset/campaign path without exact evidence",
        "150-diamond path before exact campaign block and final confirmation evidence",
        "daily prerequisite",
        "d02 prerequisite",
        "points prerequisite",
        "identical retry",
        "real-money confirmation",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(f"Hero Upgrade must forbid {marker}")


def _validate_hero_upgrade_decision_policy(payload: Mapping[str, Any]) -> None:
    """Keep product authorization separate from disabled service registration."""

    policies = {
        policy["policy_id"]: policy
        for policy in payload["policies"]
        if isinstance(policy, Mapping)
    }
    policy = policies.get("hero-upgrade-policy")
    expected = {
        "scope": "hero_upgrade.reset",
        "status": "explicitly_approved",
        "candidate_hero": "Wali",
        "normal_upgrade_count_per_reset": 3,
        "normal_upgrade_kind": "single_level",
        "normal_upgrade_verification": "baseline_and_final_cumulative_level_and_debit",
        "normal_upgrade_material": "ANTISERUM",
        "standard_evolution_materials": [
            "ANTISERUM",
            "COMBAT_MANUAL_I",
            "COMBAT_MANUAL_II",
            "COMBAT_MANUAL_III",
            "COMBAT_MANUAL_IV",
            "COMBAT_MANUAL_V",
        ],
        "evolution_only_at_displayed_cap": True,
        "evolution_counts_toward_normal_upgrade_count": False,
        "upgrade_dispatch_allowed": True,
        "approved_action_kinds": ["HERO_UPGRADE_SINGLE", "HERO_EVOLUTION_STANDARD"],
        "evidence_state": "evidence_required",
        "runtime_admission": "canonical_supervised_claim_and_current_explicit_authorization_required",
        "current_explicit_authorization_required": True,
        "canonical_supervised_claim_required": True,
        "registration_status": "NOT_REGISTERED",
        "scheduler_eligibility": False,
        "terminal_state": "home_canonical",
        "daily_prerequisite_required": False,
        "daily_ownership": None,
        "points_credit_required": False,
        "reset_campaign_diamond_path": {
            "status": "evidence_required",
            "operationally_blocked": True,
            "campaign_block_proven": False,
            "final_150_diamond_confirmation_proven": False,
            "dispatch_allowed": False,
        },
    }
    if policy is None or any(policy.get(key) != value for key, value in expected.items()):
        raise ProductAuthorityError("approved Wali product policy has invalid typed facts")


def _validate_alliance_shop_purchase_record(record: Mapping[str, Any]) -> None:
    """Validate the approved one-item Alliance Shop product envelope."""

    if (
        record["objective"] != "alliance_shop_purchase"
        or record["action"] != "select_one_current_allowlisted_alliance_offer"
        or record["recurrence"] != "daily_reset_scoped"
    ):
        raise ProductAuthorityError("Alliance Shop must use its reset-scoped one-item objective")
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["ALLIANCE_SHOP"]:
        raise ProductAuthorityError("Alliance Shop entry route must bind canonical Home")
    target = record["target"]
    if not isinstance(target, Mapping) or target != {
        "kind": "alliance_shop_purchase",
        "preferred_shop": "Weekly Offers",
        "preferred_items": ["Joy Coin", "Timed Recruit Coin", "Bioenhance Scheme"],
        "preferred_currency": "Alliance Coins",
        "fallback_shop": "Other",
        "fallback_item": "1★ Gear Enhance Material",
        "fallback_rarity": 1,
        "fallback_currency": "Alliance Coins",
        "maximum_quantity_total": 1,
        "unaffordable_preferred_permits_fallback": True,
        "premium_allowed": False,
        "cash_purchase_allowed": False,
        "alternative_currency_allowed": False,
        "policy_status": "explicitly_approved",
        "purchase_dispatch_allowed": False,
        "terminal_home": "HOME_CANONICAL",
    }:
        raise ProductAuthorityError("Alliance Shop allowlist or one-item fallback changed")
    if type(target["fallback_rarity"]) is not int or type(
        target["maximum_quantity_total"]
    ) is not int:
        raise ProductAuthorityError("Alliance Shop quantity and rarity bounds must be integers")
    if any(
        type(target[field]) is not bool
        for field in (
            "unaffordable_preferred_permits_fallback",
            "premium_allowed",
            "cash_purchase_allowed",
            "alternative_currency_allowed",
            "purchase_dispatch_allowed",
        )
    ):
        raise ProductAuthorityError("Alliance Shop approval and spending limits must be booleans")
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or type(quantity_cost.get("quantity")) is not int
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "current_observed_currency_cost"
        or cost.get("amount") is not None
        or cost.get("unit") != "Alliance Coins"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError("Alliance Shop must bind exact current cost evidence")
    effect = record["semantic_effect"]
    required_effects = {
        "exact_current_weekly_inventory_required": True,
        "exact_current_fallback_inventory_required": True,
        "preferred_offer_priority_is_source_allowlist_order": True,
        "preferred_offer_must_be_current_and_affordable": True,
        "unaffordable_preferred_offer_falls_through_to_exact_fallback": True,
        "fallback_only_when_no_affordable_preferred_offer": True,
        "fallback_offer_must_be_current_and_affordable": True,
        "no_affordable_fallback_yields_no_purchase": True,
        "changed_or_ambiguous_offer_blocks": True,
        "premium_purchase_allowed": False,
        "cash_purchase_allowed": False,
        "alternative_currency_allowed": False,
        "daily_screen_or_points_inspection_required": False,
        "one_quantity_total_across_both_paths": 1,
        "fresh_numeric_quantity_and_total_required_before_inner_buy": True,
        "selected_offer_requires_current_item_currency_cost_balance_stock_and_availability": True,
        "red_price_shortage_permits_fallback_without_owned_balance_or_stock": True,
        "owned_baseline_required": False,
        "purchase_dispatch_allowed": False,
        "exact_item_quantity_one_purchase_acknowledgement_required": True,
        "purchase_effect_independent_of_home_return": True,
        "historical_home_digest_receipts_remain_valid": True,
        "dispatch_is_not_success_proof": True,
        "canonical_home_return_required": True,
        "daily_ownership": "none",
        "identical_retry": False,
    }
    if any(key in effect for key in (
        "exact_current_item_currency_cost_balance_stock_and_availability_required",
        "paired_currency_and_item_successors_required",
        "canonical_home_successor_required",
    )):
        raise ProductAuthorityError("Alliance Shop must not require redundant purchase accounting")
    if any(
        effect.get(key) != value
        or (type(value) is bool and type(effect.get(key)) is not bool)
        or (type(value) is int and type(effect.get(key)) is not int)
        for key, value in required_effects.items()
    ):
        raise ProductAuthorityError("Alliance Shop purchase semantics exceed the approved envelope")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError("Alliance Shop must return to canonical Home")


def _validate_alliance_donation_record(record: Mapping[str, Any]) -> None:
    """Validate ten reset-scoped actual donations to the automatically selected HOT Tech."""

    if (
        record["objective"] != "alliance_tech_donation"
        or record["action"] != "make_one_individually_reconciled_ordinary_donation"
        or record["recurrence"] != "daily_reset_scoped"
    ):
        raise ProductAuthorityError("Alliance Donation must use its reset-scoped action")
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["ALLIANCE_TECH"]:
        raise ProductAuthorityError("Alliance Donation must start at canonical Home")
    target = record["target"]
    if not isinstance(target, Mapping) or target != {
        "kind": "alliance_tech_donation",
        "technology_selection": "game_automatically_selected_hot_tech",
        "rebind_current_hot_target_before_each_action": True,
        "daily_action_limit": 10,
        "ordinary_donation_quantity": 1,
        "ordinary_resource_only": True,
        "available_attempts_required": True,
        "consecutive_available_attempts_allowed": True,
        "attempts_regenerate": 1,
        "attempt_regeneration_seconds": 1800,
        "stored_attempt_cap": 20,
        "unbounded_hold_allowed": False,
        "policy_status": "explicitly_approved",
        "terminal_home": "HOME_CANONICAL",
    }:
        raise ProductAuthorityError("Alliance Donation quota, target, or attempt bounds changed")
    for field in ("daily_action_limit", "ordinary_donation_quantity", "attempts_regenerate",
                  "attempt_regeneration_seconds", "stored_attempt_cap"):
        if type(target[field]) is not int:
            raise ProductAuthorityError(f"Alliance Donation {field} must be an integer")
    if any(
        type(target[field]) is not bool
        for field in (
            "rebind_current_hot_target_before_each_action",
            "ordinary_resource_only",
            "available_attempts_required",
            "consecutive_available_attempts_allowed",
            "unbounded_hold_allowed",
        )
    ):
        raise ProductAuthorityError("Alliance Donation availability and hold limits must be booleans")
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or type(quantity_cost.get("quantity")) is not int
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "current_observed_ordinary_resource_cost"
        or cost.get("amount") is not None
        or cost.get("unit") != "ORDINARY_RESOURCE"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError("Alliance Donation must require a freshly observed ordinary cost")
    effect = record["semantic_effect"]
    required_effects = {
        "current_hot_target_numeric_ordinary_cost_and_affordability_required": True,
        "hud_resource_census_required": False,
        "resource_wallet_debit_required": False,
        "tech_progress_required": False,
        "one_confirmed_action_requires_one_consumed_attempt": True,
        "attempt_consumption_accounts_for_positively_observed_regeneration": True,
        "unchanged_attempt_count_requires_observed_timer_rollover": True,
        "count_only_distinct_effect_confirmed_actions": True,
        "daily_success_limit": 10,
        "available_attempts_may_be_spent_consecutively": True,
        "wait_required_while_attempts_remain": False,
        "regeneration_is_not_a_between_action_cooldown": True,
        "press_and_hold_donation_allowed": False,
        "ranking_or_reward_point_counters_are_success_gates": False,
        "daily_screen_or_points_inspection_required": False,
        "dispatch_is_not_success_proof": True,
        "completion_readiness_uses_own_confirmed_action_target": True,
        "canonical_home_successor_required": True,
        "daily_ownership": "none",
        "identical_retry": False,
    }
    if any(key in effect for key in (
        "current_hot_target_and_exact_resource_cost_and_balance_required",
        "one_confirmed_action_requires_exact_ordinary_resource_spend",
        "one_confirmed_action_requires_positive_current_tech_progress",
    )):
        raise ProductAuthorityError("Alliance Donation must use attempt counts, not resource or Tech deltas")
    if any(
        effect.get(key) != value
        or (type(value) is bool and type(effect.get(key)) is not bool)
        or (type(value) is int and type(effect.get(key)) is not int)
        for key, value in required_effects.items()
    ):
        raise ProductAuthorityError("Alliance Donation action counting exceeds its approved limits")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError("Alliance Donation must return to canonical Home")


def _validate_daily_shops_purchase_record(record: Mapping[str, Any]) -> None:
    """Validate the one-visit, independent Ruins and Rare Earth purchase envelope."""

    if (
        record["objective"] != "daily_shops_purchase"
        or record["action"] != "purchase_current_affordable_allowlisted_daily_shop_stock"
        or record["recurrence"] != "daily_reset_scoped"
    ):
        raise ProductAuthorityError("Daily Shops must use its reset-scoped combined objective")
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["RUINS", "EXCHANGE", "RUINS_SHOP", "RARE_EARTH_SHOP"]:
        raise ProductAuthorityError("Daily Shops must visit both tabs from the Ruins shop screen")
    target = record["target"]
    expected_shops = [
        {
            "shop": "RUINS_SHOP",
            "tab": "Ruins Shop",
            "item": "3★ Chip Enhance Material",
            "rarity": 3,
            "currency": "Ruins Coins",
            "quantity_formula": "min(current_stock, floor(current_balance / current_unit_price))",
        },
        {
            "shop": "RARE_EARTH_SHOP",
            "tab": "Rare Earth Shop",
            "item": "3★ Module Enhance Material",
            "rarity": 3,
            "currency": "Rare Earth",
            "quantity_formula": "min(current_stock, floor(current_balance / current_unit_price))",
        },
    ]
    if not isinstance(target, Mapping) or target != {
        "kind": "daily_shops_purchase",
        "shops": expected_shops,
        "one_visit_for_both_tabs": True,
        "one_purchase_selection_per_tab": True,
        "current_price_balance_and_stock_required_per_tab": True,
        "numeric_quantity_and_total_reread_before_inner_buy": True,
        "per_tab_result_independent": True,
        "maximum_quantity_is_current_stock_and_affordability_min": True,
        "premium_allowed": False,
        "policy_status": "explicitly_approved",
        "purchase_dispatch_allowed": False,
        "terminal_home": "HOME_CANONICAL",
    }:
        raise ProductAuthorityError("Daily Shops item identities or numeric quantity bounds changed")
    for shop in expected_shops:
        if type(shop["rarity"]) is not int:
            raise ProductAuthorityError("Daily Shops rarity must be an integer")
    for field in (
        "one_visit_for_both_tabs",
        "one_purchase_selection_per_tab",
        "current_price_balance_and_stock_required_per_tab",
        "numeric_quantity_and_total_reread_before_inner_buy",
        "per_tab_result_independent",
        "maximum_quantity_is_current_stock_and_affordability_min",
        "premium_allowed",
        "purchase_dispatch_allowed",
    ):
        if type(target[field]) is not bool:
            raise ProductAuthorityError(f"Daily Shops {field} must be a boolean")
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != "computed_per_tab"
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "current_observed_currency_cost"
        or cost.get("amount") is not None
        or cost.get("unit") != "CURRENT_TAB_CURRENCY"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError("Daily Shops must use current per-tab currency cost evidence")
    effect = record["semantic_effect"]
    required_effects = {
        "both_tabs_evaluated_in_one_visit": True,
        "per_tab_result_is_independent": True,
        "tab_quantity_is_min_stock_and_affordability": True,
        "quantity_must_equal_current_affordable_stock_cap": True,
        "zero_affordable_or_unavailable_tab_is_skipped": True,
        "numeric_quantity_and_total_must_match_before_inner_buy": True,
        "changed_or_ambiguous_tab_blocks_without_substitution": True,
        "premium_purchase_allowed": False,
        "tab_status_and_purchase_acknowledgement_stock_effects_reconciled_separately": True,
        "exact_item_and_quantity_purchase_acknowledgement_required_per_tab": True,
        "decreased_stock_required_per_purchased_tab": True,
        "owned_baseline_required": False,
        "wallet_debit_required": False,
        "confirmed_or_already_confirmed_tab_with_blocked_sibling_is_partial_deferred": True,
        "uncertain_tab_effect_is_not_retried": True,
        "current_native_gameplay_effect_is_only_readiness_basis": True,
        "daily_screen_or_points_inspection_required": False,
        "daily_ownership": "none",
        "purchase_dispatch_allowed": False,
        "canonical_home_successor_required": True,
        "dispatch_is_not_success_proof": True,
        "identical_retry": False,
    }
    if "tab_status_and_item_currency_effects_reconciled_separately" in effect:
        raise ProductAuthorityError("Daily Shops must not require paired item and currency accounting")
    if any(
        effect.get(key) != value
        or (type(value) is bool and type(effect.get(key)) is not bool)
        for key, value in required_effects.items()
    ):
        raise ProductAuthorityError("Daily Shops tab semantics exceed the approved envelope")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError("Daily Shops must return to canonical Home")

def _validate_rare_earth_shop_purchase_record(record: Mapping[str, Any]) -> None:
    """Validate an unresolved, non-dispatch Rare Earth Shop candidate."""

    if record["objective"] != "rare_earth_shop_purchase":
        raise ProductAuthorityError(
            "Rare Earth Shop record objective must be rare_earth_shop_purchase"
        )
    if record["action"] != "observe_one_rare_earth_shop_purchase_candidate":
        raise ProductAuthorityError(
            "Rare Earth Shop action must remain observation-only until product approval"
        )
    if record["recurrence"] != "daily_reset_scoped":
        raise ProductAuthorityError(
            "Rare Earth Shop recurrence must be daily_reset_scoped"
        )
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["RARE_EARTH_SHOP"]:
        raise ProductAuthorityError(
            "Rare Earth Shop entry route must bind canonical Home to Rare Earth Shop"
        )
    target = record["target"]
    if (
        not isinstance(target, Mapping)
        or target.get("kind") != "rare_earth_shop_purchase"
        or target.get("shop") != "RARE_EARTH_SHOP"
        or target.get("candidate_item") != "unknown_current_three_star_item"
        or target.get("candidate_rarity") != "3_STAR"
        or target.get("candidate_currency") != "unknown_current_currency"
        or target.get("candidate_cost") is not None
        or target.get("quantity") != 1
        or target.get("policy_status") != "unresolved_user_decision"
        or target.get("purchase_dispatch_allowed") is not False
        or target.get("terminal_home") != "HOME_CANONICAL"
    ):
        raise ProductAuthorityError(
            "Rare Earth Shop target must preserve unknown item and cost bounds"
        )
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "unresolved_currency_cost"
        or cost.get("amount") is not None
        or cost.get("unit") != "UNKNOWN_CURRENT_CURRENCY"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError(
            "Rare Earth Shop candidate must keep unknown cost fail-closed"
        )
    effect = record["semantic_effect"]
    required_effects = {
        "effect_ordinal": 1,
        "offer_observation_successor_required": True,
        "exact_item_evidence_required": True,
        "exact_cost_evidence_required": True,
        "balance_evidence_required": True,
        "quantity_one_required": True,
        "purchase_dispatch_allowed": False,
        "currency_delta_required_for_purchase_proof": True,
        "item_delta_required_for_purchase_proof": True,
        "canonical_home_successor_required": True,
        "dispatch_is_not_success_proof": True,
        "daily_ownership": "none",
        "identical_retry": False,
    }
    if any(effect.get(key) != value for key, value in required_effects.items()):
        raise ProductAuthorityError(
            "Rare Earth Shop candidate must stay evidence-gated and non-dispatching"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Rare Earth Shop terminal requirement must return to canonical Home"
        )
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "buy",
        "purchase dispatch",
        "currency spend",
        "premium offer",
        "unknown item",
        "ambiguous item",
        "unknown cost",
        "ambiguous cost",
        "unknown currency",
        "insufficient balance",
        "identical retry",
        "real-money",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(
                f"Rare Earth Shop candidate must forbid {marker} actions"
            )



def _validate_ruins_shop_purchase_record(record: Mapping[str, Any]) -> None:
    """Validate an unresolved, non-dispatch Ruins Shop purchase candidate."""

    if record["objective"] != "ruins_shop_purchase":
        raise ProductAuthorityError(
            "Ruins Shop record objective must be ruins_shop_purchase"
        )
    if record["action"] != "observe_one_ruins_shop_purchase_candidate":
        raise ProductAuthorityError(
            "Ruins Shop action must remain observation-only until product approval"
        )
    if record["recurrence"] != "daily_reset_scoped":
        raise ProductAuthorityError("Ruins Shop recurrence must be daily_reset_scoped")
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["RUINS_SHOP"]:
        raise ProductAuthorityError(
            "Ruins Shop entry route must bind canonical Home to Ruins Shop"
        )
    target = record["target"]
    if (
        not isinstance(target, Mapping)
        or target.get("kind") != "ruins_shop_purchase"
        or target.get("shop") != "RUINS_SHOP"
        or target.get("candidate_item") != "three_star_chip_material"
        or target.get("candidate_currency") != "RUINS_COINS"
        or target.get("candidate_cost") != 15
        or target.get("quantity") != 1
        or target.get("policy_status") != "unresolved_user_decision"
        or target.get("purchase_dispatch_allowed") is not False
        or target.get("terminal_home") != "HOME_CANONICAL"
    ):
        raise ProductAuthorityError(
            "Ruins Shop target must preserve unresolved three-star Chip and 15-coin bounds"
        )
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "candidate_currency_cost"
        or cost.get("amount") != 15
        or cost.get("unit") != "RUINS_COINS"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError(
            "Ruins Shop candidate must preserve one 15 RUINS_COINS cost"
        )
    effect = record["semantic_effect"]
    required_effects = {
        "effect_ordinal": 1,
        "offer_observation_successor_required": True,
        "exact_cost_evidence_required": True,
        "balance_evidence_required": True,
        "purchase_dispatch_allowed": False,
        "currency_delta_required_for_purchase_proof": True,
        "daily_progress_successor_required_for_purchase_proof": True,
        "canonical_home_successor_required": True,
        "dispatch_is_not_success_proof": True,
        "daily_ownership": "none",
        "identical_retry": False,
    }
    if any(effect.get(key) != value for key, value in required_effects.items()):
        raise ProductAuthorityError(
            "Ruins Shop candidate must stay evidence-gated and non-dispatching"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Ruins Shop terminal requirement must return to canonical Home"
        )
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "buy",
        "purchase dispatch",
        "currency spend",
        "premium offer",
        "unknown",
        "ambiguous",
        "insufficient balance",
        "identical retry",
        "real-money",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(
                f"Ruins Shop candidate must forbid {marker} actions"
            )



def _validate_nanoweapon_normal_craft_record(record: Mapping[str, Any]) -> None:
    """Validate one reset-scoped Normal Craft action and its maintenance prerequisite."""

    if (
        record["record_revision"] != "nanoweapon_normal_craft-v2"
        or record["objective"] != "nanoweapon_normal_craft"
        or record["action"] != "start_one_normal_nanoweapon_craft"
        or record["recurrence"] != "daily_reset_scoped"
    ):
        raise ProductAuthorityError("Nanoweapon Normal Craft must use its v2 own-action identity")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_CANONICAL"]
        or route.get("route") != ["GEAR_FACTORY", "NANOWEAPON", "NORMAL_CRAFT"]
    ):
        raise ProductAuthorityError(
            "Nanoweapon entry route must bind canonical Home to Normal Craft"
        )
    expected_maintenance = {
        "product_record_id": "nano_material_production",
        "product_record_revision": "nano_material_production-v1",
        "required_same_visit": True,
        "separate_authorization_required": True,
        "positive_effect_must_be_reconciled_before_craft": True,
        "normal_craft_substitution_allowed": False,
        "normal_craft_reset_allowance_consumed": False,
    }
    expected_target = {
        "kind": "nanoweapon_normal_craft",
        "craft_mode": "NORMAL_CRAFT",
        "completed_claim_on_entry": True,
        "parts_required": 100,
        "parts_unit": "NANO_PARTS",
        "maximum_active_crafts": 1,
        "maximum_starts_per_reset": 1,
        "craft_duration_seconds": 43200,
        "exclusive_craft_allowed": False,
        "rotating_display_selection_allowed": False,
        "insufficient_parts_defer": True,
        "disabled_craft_defer": True,
        "prior_material_production": expected_maintenance,
        "terminal_home": "HOME_CANONICAL",
    }
    target = record["target"]
    if not isinstance(target, Mapping) or dict(target) != expected_target:
        raise ProductAuthorityError(
            "Nanoweapon Normal Craft target or prior maintenance composition changed"
        )
    prior_maintenance = target["prior_material_production"]
    if any(
        type(target[field]) is not int
        for field in (
            "parts_required",
            "maximum_active_crafts",
            "maximum_starts_per_reset",
            "craft_duration_seconds",
        )
    ):
        raise ProductAuthorityError("Nanoweapon Normal Craft limits must be integers")
    if any(
        type(target[field]) is not bool
        for field in (
            "completed_claim_on_entry",
            "exclusive_craft_allowed",
            "rotating_display_selection_allowed",
            "insufficient_parts_defer",
            "disabled_craft_defer",
        )
    ) or any(
        type(prior_maintenance[field]) is not bool
        for field in (
            "required_same_visit",
            "separate_authorization_required",
            "positive_effect_must_be_reconciled_before_craft",
            "normal_craft_substitution_allowed",
            "normal_craft_reset_allowance_consumed",
        )
    ):
        raise ProductAuthorityError("Nanoweapon Normal Craft composition flags must be booleans")
    expected_quantity_cost = {
        "quantity": 1,
        "cost": {
            "kind": "exact_material",
            "amount": 100,
            "unit": "NANO_PARTS",
            "free_only": False,
        },
    }
    quantity_cost = record["quantity_cost"]
    if not isinstance(quantity_cost, Mapping) or dict(quantity_cost) != expected_quantity_cost:
        raise ProductAuthorityError("Nanoweapon Normal Craft must bind exact 100 NANO_PARTS")
    if (
        type(quantity_cost["quantity"]) is not int
        or type(quantity_cost["cost"]["amount"]) is not int
        or type(quantity_cost["cost"]["free_only"]) is not bool
    ):
        raise ProductAuthorityError("Nanoweapon Normal Craft costs must be integers and booleans")
    expected_effect = {
        "effect_ordinal": 1,
        "completed_claim_successor_required": True,
        "exact_parts_consumption_required": True,
        "single_active_craft_required": True,
        "single_start_per_reset_required": True,
        "exact_duration_required": True,
        "own_normal_craft_start_successor_required": True,
        "prior_material_production_reconciled_before_craft": True,
        "maintenance_does_not_satisfy_normal_craft": True,
        "maintenance_does_not_consume_normal_craft_reset_allowance": True,
        "no_currency_box_or_item_input": True,
        "dispatch_is_not_success_proof": True,
        "daily_ownership": "none",
        "identical_retry": False,
    }
    effect = record["semantic_effect"]
    if not isinstance(effect, Mapping) or dict(effect) != expected_effect:
        raise ProductAuthorityError(
            "Nanoweapon Normal Craft must require its own successor without Daily coupling"
        )
    if type(effect["effect_ordinal"]) is not int or any(
        type(effect[field]) is not bool
        for field in (
            "completed_claim_successor_required",
            "exact_parts_consumption_required",
            "single_active_craft_required",
            "single_start_per_reset_required",
            "exact_duration_required",
            "own_normal_craft_start_successor_required",
            "prior_material_production_reconciled_before_craft",
            "maintenance_does_not_satisfy_normal_craft",
            "maintenance_does_not_consume_normal_craft_reset_allowance",
            "no_currency_box_or_item_input",
            "dispatch_is_not_success_proof",
            "identical_retry",
        )
    ):
        raise ProductAuthorityError("Nanoweapon Normal Craft effect flags must be typed")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Nanoweapon Normal Craft must return to canonical Home"
        )


def _validate_nano_material_production_record(record: Mapping[str, Any]) -> None:
    """Validate independent zero-resource six-hour material maintenance."""

    if record["objective"] != "nano_material_production_maintenance":
        raise ProductAuthorityError(
            "Nano Material record objective must be nano_material_production_maintenance"
        )
    if record["action"] != "maintain_one_nano_material_production":
        raise ProductAuthorityError(
            "Nano Material action must be maintain_one_nano_material_production"
        )
    if record["recurrence"] != "cooldown_pulse":
        raise ProductAuthorityError("Nano Material recurrence must be cooldown_pulse")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_CANONICAL"]
        or route.get("route") != ["NANOWEAPON", "MATERIAL_PRODUCTION"]
    ):
        raise ProductAuthorityError(
            "Nano Material entry route must bind canonical Home to Material Production"
        )
    target = record["target"]
    if (
        target.get("kind") != "nano_material_production"
        or target.get("tab") != "MATERIAL_PRODUCTION"
        or target.get("maximum_active_productions") != 1
        or target.get("production_duration_seconds") != 21600
        or target.get("completed_claim_allowed") is not True
        or target.get("idle_start_allowed") is not True
        or target.get("active_due_time_refresh_allowed") is not True
        or target.get("base_resource_cost") != 0
        or target.get("boxes_allowed") is not False
        or target.get("currency_cost") != 0
        or target.get("item_cost") != 0
        or target.get("daily_craft_ownership") != "separate_nanoweapon_product"
        or target.get("terminal_home") != "HOME_CANONICAL"
    ):
        raise ProductAuthorityError(
            "Nano Material target must bind one zero-resource six-hour production"
        )
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "zero_resource_maintenance"
        or cost.get("amount") != 0
        or cost.get("unit") != "resource_or_currency"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError(
            "Nano Material must bind one free zero-resource maintenance batch"
        )
    effect = record["semantic_effect"]
    required_effects = (
        "completed_claim_successor_allowed",
        "idle_start_successor_allowed",
        "active_due_time_successor_required",
        "single_active_production_required",
        "exact_duration_required",
        "zero_resource_cost_required",
        "canonical_home_successor_required",
        "dispatch_is_not_success_proof",
    )
    if (
        effect.get("effect_ordinal") != 1
        or any(effect.get(field) is not True for field in required_effects)
        or effect.get("daily_ownership") != "none"
        or effect.get("identical_retry") is not False
    ):
        raise ProductAuthorityError(
            "Nano Material successor, cost, or retry safety effect is incomplete"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Nano Material terminal requirement must return to canonical Home"
        )


def _validate_zombie_lair_record(record: Mapping[str, Any]) -> None:
    """Validate bounded notification-driven Zombie Lair authority."""

    if record["objective"] != "zombie_lair_quick_join":
        raise ProductAuthorityError(
            "Zombie Lair record objective must be zombie_lair_quick_join"
        )
    if record["action"] != "join_one_eligible_zombie_lair":
        raise ProductAuthorityError(
            "Zombie Lair action must be join_one_eligible_zombie_lair"
        )
    if record["recurrence"] != "home_notification_pulse":
        raise ProductAuthorityError(
            "Zombie Lair recurrence must be home_notification_pulse"
        )
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_CANONICAL"]
        or route.get("route") != ["ZOMBIE_LAIR"]
    ):
        raise ProductAuthorityError(
            "Zombie Lair entry route must bind canonical Home to notifications"
        )
    target = record["target"]
    if (
        target.get("kind") != "zombie_lair"
        or target.get("minimum_level") != 30
        or target.get("maximum_level") != 55
        or target.get("join_control") != "QUICK_JOIN"
        or target.get("stamina_per_join") != 28
        or target.get("maximum_join_count")
        != "min(eligible_count, floor(current_stamina/28))"
        or target.get("formation") != "quick_join_configured_formation"
        or target.get("daily_completion_owner")
        != "first_successful_eligible_join_per_reset"
        or target.get("maintenance_owner") != "home_notification_pulse"
        or target.get("static_daily_row") != "forbidden"
        or target.get("level_60") != "forbidden"
        or target.get("stamina_refill") != "forbidden"
        or target.get("safe_terminal")
        != ["HOME_CANONICAL", "SAFE_HOME_EQUIVALENT"]
    ):
        raise ProductAuthorityError(
            "Zombie Lair target must bind eligible Quick Join levels and exact stamina"
        )
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != "bounded_eligible_joins"
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "fixed_stamina_per_join"
        or cost.get("amount") != 28
        or cost.get("unit") != "STAMINA"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError(
            "Zombie Lair must bind bounded 28-stamina joins"
        )
    effect = record["semantic_effect"]
    required_effects = (
        "eligible_level_range_required",
        "quick_join_identity_required",
        "stamina_delta_required",
        "daily_completion_successor_required",
        "maintenance_successor_required",
        "no_refill_required",
        "no_level_60_required",
        "dispatch_is_not_success_proof",
    )
    if (
        effect.get("effect_ordinal") != 1
        or any(effect.get(field) is not True for field in required_effects)
        or effect.get("daily_ownership")
        != "first_successful_eligible_join_per_reset"
        or effect.get("identical_retry") is not False
    ):
        raise ProductAuthorityError(
            "Zombie Lair successor, ownership, or retry safety effect is incomplete"
        )
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner")
        != "first_successful_eligible_join_per_reset"
        or ownership.get("point_credit_trigger")
        != "first_successful_eligible_join_per_reset"
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError(
            "Zombie Lair Daily ownership must bind the first successful join"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Zombie Lair terminal requirement must return to canonical Home"
        )
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "level 60",
        "unknown level",
        "stamina refill",
        "item refill",
        "currency refill",
        "formation",
        "unknown successor",
        "identical retry",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(
                f"Zombie Lair forbidden actions must include {marker}"
            )

def _validate_world_map_navigation_record(record: Mapping[str, Any]) -> None:
    """Validate navigation-only Home-to-World/Search-to-Home authority."""

    if record["objective"] != "world_map_navigation_round_trip":
        raise ProductAuthorityError(
            "World Map record objective must be world_map_navigation_round_trip"
        )
    if record["action"] != "navigate_world_search_round_trip":
        raise ProductAuthorityError(
            "World Map action must be navigate_world_search_round_trip"
        )
    if record["recurrence"] != "navigation_session":
        raise ProductAuthorityError("World Map recurrence must be navigation_session")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_READY"]
        or route.get("route") != ["WORLD", "SEARCH", "WORLD", "HOME"]
    ):
        raise ProductAuthorityError(
            "World Map entry route must bind HOME_READY to World/Search/Home"
        )
    target = record["target"]
    if (
        target.get("kind") != "world_map_navigation"
        or target.get("search_control") != "WORLD_SEARCH"
        or target.get("atlas_authority") != "out_of_scope"
        or target.get("march_authority") != "forbidden"
    ):
        raise ProductAuthorityError("World Map target authority is not navigation-only")
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 0
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "none"
        or cost.get("amount") != 0
        or cost.get("unit") != "none"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("World Map navigation must be zero-cost")
    effect = record["semantic_effect"]
    if effect.get("effect_ordinal") != 1:
        raise ProductAuthorityError("World Map navigation effect ordinal must be one")
    required_effects = (
        "navigation_only",
        "world_successor_required",
        "search_successor_required",
        "home_successor_required",
        "popup_successor_required",
        "dispatch_is_not_success_proof",
        "no_resource_input",
        "no_march_input",
        "no_attack_input",
        "no_stamina_input",
        "no_ap_input",
    )
    if any(effect.get(field) is not True for field in required_effects):
        raise ProductAuthorityError("World Map navigation successor or safety effect is incomplete")
    if effect.get("identical_retry") is not False:
        raise ProductAuthorityError("World Map navigation must deny identical retry")
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError("World Map navigation must not own Daily progress")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "World Map navigation terminal requirement must return to canonical Home"
        )
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "march",
        "attack",
        "stamina",
        "ap",
        "resource",
        "currency",
        "combat",
        "node",
        "unknown",
        "ambiguous",
        "identical retry",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(
                f"World Map forbidden actions must include {marker}"
            )

def _validate_vip_points_popup_dismissal_record(record: Mapping[str, Any]) -> None:
    """Validate one bounded, navigation-only VIP Get Pts popup dismissal."""

    if record["objective"] != "vip_points_popup_dismissal":
        raise ProductAuthorityError(
            "VIP popup record objective must be vip_points_popup_dismissal"
        )
    if record["action"] != "dismiss_one_allowlisted_vip_points_popup":
        raise ProductAuthorityError(
            "VIP popup action must dismiss_one_allowlisted_vip_points_popup"
        )
    if record["recurrence"] != "navigation_session":
        raise ProductAuthorityError("VIP popup recurrence must be navigation_session")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities")
        != ["HOME_READY", "HOME_LOCALIZED", "HOME_CANONICAL"]
        or route.get("target") != "HOME"
        or route.get("route") != ["VIP_POINTS_POPUP"]
    ):
        raise ProductAuthorityError(
            "VIP popup entry route must bind typed Home authorities to VIP_POINTS_POPUP"
        )
    target = record["target"]
    if (
        target.get("kind") != "vip_points_popup"
        or target.get("popup_identity") != "VIP_POINTS_GET_PTS"
        or target.get("close_control") != "RESET_POPUP_CLOSE"
        or target.get("eligibility") != "fresh_current_frame_allowlisted_popup"
        or target.get("maximum_inputs") != 1
        or target.get("successor") != "recognized_source_context_without_popup"
    ):
        raise ProductAuthorityError(
            "VIP popup target must require one fresh allowlisted Get Pts popup"
        )
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 0
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "none"
        or cost.get("amount") != 0
        or cost.get("unit") != "none"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("VIP popup dismissal must be zero-cost")
    effect = record["semantic_effect"]
    required_effects = (
        "navigation_only",
        "popup_absent_successor_required",
        "source_context_successor_required",
        "bounded_single_close",
        "no_resource_input",
        "no_march_input",
        "no_attack_input",
        "no_stamina_input",
        "no_ap_input",
        "no_currency_input",
        "dispatch_is_not_success_proof",
    )
    if effect.get("effect_ordinal") != 1 or any(
        effect.get(field) is not True for field in required_effects
    ):
        raise ProductAuthorityError(
            "VIP popup dismissal successor or safety effect is incomplete"
        )
    if effect.get("identical_retry") is not False:
        raise ProductAuthorityError("VIP popup dismissal must deny identical retry")
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError("VIP popup dismissal must not own Daily progress")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "VIP popup terminal requirement must return to canonical Home"
        )
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "unknown",
        "ambiguous",
        "generic close",
        "multiple popup",
        "resource",
        "march",
        "attack",
        "stamina",
        "ap",
        "currency",
        "combat",
        "identical retry",
        "real-money",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(
                f"VIP popup forbidden actions must include {marker}"
            )


def _validate_campaign_ap_record(record: Mapping[str, Any]) -> None:
    """Validate bounded AP-funded Auto Battle product authority."""

    if record["objective"] != "campaign_ap_auto_battle":
        raise ProductAuthorityError(
            "Campaign AP record objective must be campaign_ap_auto_battle"
        )
    if record["action"] != "dispatch_campaign_ap_auto_battle":
        raise ProductAuthorityError(
            "Campaign AP action must be dispatch_campaign_ap_auto_battle"
        )
    if record["recurrence"] != "pulse_driven_ap_recovery":
        raise ProductAuthorityError(
            "Campaign AP recurrence must be pulse_driven_ap_recovery"
        )
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != ["HOME_CANONICAL"] or route.get(
        "route"
    ) != ["CAMPAIGN", "STORY", "CONFIGURED_STAGE"]:
        raise ProductAuthorityError(
            "Campaign AP entry route must bind canonical Home to configured Story stage"
        )
    target = record.get("target")
    if not isinstance(target, Mapping) or (
        target.get("kind") != "campaign_ap"
        or target.get("eligibility") != "current_ap_covers_configured_stage_cost"
        or target.get("control") != "Auto Battle"
        or target.get("quantity") != 1
        or target.get("supported_story_destinations")
        != ["1-20-9", "1-15-9", "2-2-9"]
        or target.get("stage_costs") != {"1-15-9": 14, "1-20-9": 16, "2-2-9": 20}
        or target.get("maximum_ap") != 120
        or target.get("refill_allowed") is not False
        or target.get("execution_mode") != "auto_battle"
    ):
        raise ProductAuthorityError(
            "Campaign AP target must bind approved stages, costs, budget, and Auto Battle"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError("Campaign AP quantity must be exactly one action")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "owned_campaign_ap"
        or cost.get("amount") != "configured_stage_cost"
        or cost.get("unit") != "AP"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError(
            "Campaign AP must bind one known AP cost without refill or free-only semantics"
        )
    effect = record["semantic_effect"]
    if (
        effect.get("effect_ordinal") != 1
        or effect.get("maximum_ap") != 120
        or effect.get("regeneration_seconds_per_ap") != 360
        or effect.get("exact_stage_cost_required") is not True
        or effect.get("exact_ap_delta_required") is not True
        or effect.get("result_successor_required") is not True
        or effect.get("repeat_while_affordable") is not True
        or effect.get("no_refill") is not True
        or effect.get("dispatch_is_not_success_proof") is not True
        or effect.get("identical_retry") is not False
    ):
        raise ProductAuthorityError(
            "Campaign AP must require exact cost, AP delta, result successor, and retry denial"
        )
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError(
            "Campaign AP must not own selected Daily or point credit"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Campaign AP terminal requirement must return to canonical Home"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in (
        "sweep",
        "blitz",
        "auto complete",
        "ap refill",
        "unknown stage",
        "unknown cost",
        "ultimate challenge",
        "identical retry",
        "real-money",
    ):
        if marker not in forbidden_lower:
            raise ProductAuthorityError(f"Campaign AP must forbid {marker} controls")


def _validate_bioenhancer_research_record(record: Mapping[str, Any]) -> None:
    """Validate one direct, zero-cost Bioenhancer Free Research pulse."""

    if record["objective"] != "bioenhancer_research_one_free_pulse":
        raise ProductAuthorityError(
            "Bioenhancer record objective must be bioenhancer_research_one_free_pulse"
        )
    if record["action"] != "dispatch_one_free_bioenhancer_research":
        raise ProductAuthorityError(
            "Bioenhancer action must be dispatch_one_free_bioenhancer_research"
        )
    if record["recurrence"] != "cooldown_pulse":
        raise ProductAuthorityError("Bioenhancer recurrence must be cooldown_pulse")
    route = record["semantic_entry_route"]
    if route.get("source_home_authorities") != [
        "HOME_READY",
        "HOME_LOCALIZED",
        "HOME_CANONICAL",
    ] or route.get("route") != ["RESEARCH_LAB", "BIOENHANCER"]:
        raise ProductAuthorityError(
            "Bioenhancer entry route must bind Home to Research Lab and Bioenhancer"
        )
    target = record.get("target")
    if not isinstance(target, Mapping) or (
        target.get("kind") != "bioenhancer_research"
        or target.get("eligibility") != "one_free_attempt_available"
        or target.get("control") != "Free Research 1x"
        or target.get("quantity") != 1
    ):
        raise ProductAuthorityError(
            "Bioenhancer target must require one currently eligible free Research 1x"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError("Bioenhancer quantity must be exactly one")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "zero_cost_free_bioenhancer_research"
        or cost.get("amount") != 0
        or cost.get("unit") != "Free Research 1x"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("Bioenhancer must be free and zero-cost")
    effect = record["semantic_effect"]
    if (
        effect.get("effect_ordinal") != 1
        or effect.get("cooldown_successor_required") is not True
        or effect.get("count_text_not_sufficient") is not True
        or effect.get("dispatch_is_not_success_proof") is not True
        or effect.get("success_requires") != "positive_free_cooldown_successor"
        or effect.get("paid_fallback") is not False
        or effect.get("ten_x_fallback") is not False
        or effect.get("identical_retry") is not False
    ):
        raise ProductAuthorityError(
            "Bioenhancer must type one free action, cooldown successor, dispatch separation, and retry/cost boundaries"
        )
    ownership = record["daily_ownership"]
    if (
        ownership.get("daily_owner") is not None
        or ownership.get("point_credit_trigger") is not None
        or ownership.get("selected_daily_prerequisite") is not False
    ):
        raise ProductAuthorityError("Bioenhancer must not own selected Daily")
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Bioenhancer terminal requirement must return to canonical Home"
        )
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    for marker in (
        "paid",
        "10x",
        "unknown",
        "contradictory",
        "stale",
        "identical retry",
        "real-money",
    ):
        if marker not in forbidden_lower:
            raise ProductAuthorityError(f"Bioenhancer must forbid {marker} actions")


def _validate_ruins_challenge_record(record: Mapping[str, Any]) -> None:
    """Validate reset-scoped Ruins challenge and independent ready-chest rules."""
    if record["record_revision"] != "ruins_challenge-v2":
        raise ProductAuthorityError("Ruins Challenge product record revision is frozen")

    if record["objective"] != "ruins_challenge_and_ready_stage_chest_maintenance":
        raise ProductAuthorityError("Ruins objective must bind its challenge and chest visit")
    if record["action"] != "dispatch_current_zero_cost_npc_challenge_then_claim_green_ready_stage_chests":
        raise ProductAuthorityError("Ruins action must attempt the current challenge first")
    if record["recurrence"] != "reset_scoped_cooldown_pulse":
        raise ProductAuthorityError("Ruins recurrence must be a reset-scoped cooldown pulse")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities")
        != ["HOME_READY", "HOME_LOCALIZED", "HOME_CANONICAL"]
        or route.get("route") != ["RUINS", "CHALLENGE"]
    ):
        raise ProductAuthorityError("Ruins route must bind Home to the Challenge surface")
    target = record.get("target")
    if not isinstance(target, Mapping) or any(
        target.get(key) != value
        for key, value in {
            "kind": "ruins_challenge",
            "challenge_identity": "current_allowlisted_npc",
            "challenge_control": "Attack/Dispatch",
            "challenge_eligibility": "current_day_current_zero_cost_npc_only",
            "challenge_quantity": 1,
            "challenge_reset_scoped": True,
            "overview": "Stage Overview",
            "chest_categories": "each_independently_observed_category",
            "chest_eligibility": "visible_green_ready",
            "chest_claims_per_category_per_reset": 1,
            "challenge_unavailable_behavior": "continue_to_independently_ready_overview_chests",
        }.items()
    ):
        raise ProductAuthorityError(
            "Ruins target must bind one current free NPC challenge and green-ready categories"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") is not None:
        raise ProductAuthorityError("Ruins quantity must remain per-action, not one route-wide claim")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or any(
        cost.get(key) != value
        for key, value in {
            "kind": "zero_cost_npc_challenge_and_green_ready_stage_chests",
            "amount": 0,
            "unit": "NPC challenge or stage chest",
            "free_only": True,
        }.items()
    ):
        raise ProductAuthorityError("Ruins challenge and ready chests must be zero-cost only")
    effect = record["semantic_effect"]
    required_effects = {
        "effect_ordinal": 1,
        "reset_scope": "daily_reset",
        "challenge_before_overview": True,
        "current_day_and_exact_npc_required": True,
        "zero_cost_and_attack_dispatch_required": True,
        "dispatch_limit_per_exact_stage_per_reset": 1,
        "verified_win_requires_fresh_next_permitted_stage": True,
        "first_recognized_loss_finishes_challenge_for_reset": True,
        "reset_npc_stage_identity_persisted": True,
        "confirmed_legacy_result_unrecoverable_stops_challenge_only": True,
        "finite_visit_budget_pause_is_resumable": True,
        "budget_pause_is_not_daily_completion": True,
        "unsent_plan_is_not_unknown": True,
        "medal_or_resource_arithmetic_required": False,
        "full_npc_troop_capacity_required": False,
        "skip_battle_required": False,
        "twelve_category_coverage_required": False,
        "weekly_reward_wording_required": False,
        "positive_result_for_same_challenge_required": True,
        "recognized_loss_counts_as_participation": True,
        "challenge_unavailable_does_not_block_chest_maintenance": True,
        "challenge_unavailability_does_not_fabricate_a_result": True,
        "challenge_success_not_required_for_ready_chests": True,
        "overview_categories_observed_independently": True,
        "only_green_ready_category_claimed": True,
        "category_successor_required": True,
        "per_category_claim_and_unknown_state_persisted": True,
        "unknown_consequential_effects_block_restart_retry": True,
        "dispatch_is_not_success_proof": True,
        "daily_screen_required": False,
        "daily_provider_required": False,
        "objective_attribution": False,
        "points_attribution": False,
        "identical_retry": False,
    }
    if any(key not in effect or effect[key] != value for key, value in required_effects.items()):
        raise ProductAuthorityError(
            "Ruins effect must keep challenge participation and each ready chest independent"
        )
    if "attempt_limit_per_reset" in effect:
        raise ProductAuthorityError("Ruins must not impose a reset-wide attempt cap")
    ownership = record["daily_ownership"]
    if any(
        ownership.get(key) is not None
        for key in ("daily_owner", "point_credit_trigger")
    ):
        raise ProductAuthorityError("Ruins must not assign Daily ownership or point credit")
    if record["terminal_requirement"].get("return_required") is not True:
        raise ProductAuthorityError("Ruins must return to canonical Home")


def _validate_alliance_help_record(record: Mapping[str, Any]) -> None:
    """Validate ten reset-scoped free Help requests with durable partial progress."""
    if record["record_revision"] != "alliance_help-v2":
        raise ProductAuthorityError("Alliance Help product record revision is frozen")

    if record["objective"] != "alliance_help_ten_free_requests":
        raise ProductAuthorityError("Alliance Help objective must count ten free requests")
    if record["action"] != "complete_current_free_alliance_help_requests":
        raise ProductAuthorityError("Alliance Help action must complete actual free requests")
    if record["recurrence"] != "reset_scoped_cooldown_pulse":
        raise ProductAuthorityError("Alliance Help recurrence must be a reset-scoped cooldown pulse")
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities")
        != ["HOME_READY", "HOME_LOCALIZED", "HOME_CANONICAL"]
        or route.get("route") != ["ALLIANCE", "HELP"]
    ):
        raise ProductAuthorityError("Alliance Help route must bind Home to the Help surface")
    target = record.get("target")
    if not isinstance(target, Mapping) or any(
        target.get(key) != value
        for key, value in {
            "kind": "alliance_help",
            "source": "fresh_current_alliance_help_screen",
            "help_all_control": "Help All",
            "help_all_count_rule": "actual_numeric_result_credit_without_pre_dispatch_census",
            "help_all_preferred": True,
            "individual_control": "Help",
            "successful_request_goal": 10,
            "request_unit": "successfully_completed_free_request",
            "stop_when": "goal_reached_or_free_help_disappears_or_one_help_all_batch",
            "reset_scoped_progress": True,
        }.items()
    ):
        raise ProductAuthorityError(
            "Alliance Help target must bind the exact free Help All or individual request"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 10:
        raise ProductAuthorityError("Alliance Help quota must be ten successful requests")
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or any(
        cost.get(key) != value
        for key, value in {
            "kind": "zero_cost_free_alliance_help",
            "amount": 0,
            "unit": "Help request",
            "free_only": True,
        }.items()
    ):
        raise ProductAuthorityError("Alliance Help must be free and zero-cost")
    effect = record["semantic_effect"]
    required_effects = {
        "effect_ordinal": 1,
        "reset_scope": "daily_reset",
        "successful_request_goal": 10,
        "success_unit": "positive_attributable_free_help_operation",
        "help_all_requires_exact_request_count_known": False,
        "request_census_required": False,
        "coin_balance_or_delta_required": False,
        "operation_ordinal_minimum": 1,
        "operation_ordinal_ceiling": None,
        "operation_identity_independent_of_proven_count": True,
        "actual_numeric_credit_not_clipped_to_goal": True,
        "positive_unknown_count_batch_confirmed_and_deferred": True,
        "unknown_count_batch_is_not_unknown_effect": True,
        "maximum_help_all_batches_per_visit": 1,
        "row_disappearance_alone_is_not_success": True,
        "fresh_observation_before_each_dispatch": True,
        "exact_no_requests_screen_forbids_dispatch": True,
        "individual_help_one_request_at_a_time": True,
        "confirmed_partial_quota_persisted_across_restart": True,
        "transport_call_is_not_success": True,
        "static_help_screen_is_not_success": True,
        "stop_after_ten_successful_requests": True,
        "stop_when_free_help_disappears": True,
        "unknown_target_or_cost_blocks_dispatch": True,
        "unknown_overlay_or_stale_source_blocks_dispatch": True,
        "unknown_successor_persisted_and_identical_retry_denied": True,
        "payment_purchase_donation_and_gameplay_claim_allowed": False,
        "dispatch_is_not_success_proof": True,
        "daily_screen_required": False,
        "daily_provider_required": False,
        "objective_attribution": False,
        "points_attribution": False,
        "identical_retry": False,
    }
    if any(key not in effect or effect[key] != value for key, value in required_effects.items()):
        raise ProductAuthorityError(
            "Alliance Help must preserve actual credit, bounded batches and restart-safe operations"
        )
    if "successful_request_ceiling" in effect or "individual_request_ceiling" in target:
        raise ProductAuthorityError("Alliance Help goal must not cap batch credit or operation ordinals")
    ownership = record["daily_ownership"]
    if any(
        ownership.get(key) is not None
        for key in ("daily_owner", "point_credit_trigger")
    ):
        raise ProductAuthorityError("Alliance Help must not assign Daily ownership or point credit")
    if record["terminal_requirement"].get("return_required") is not True:
        raise ProductAuthorityError("Alliance Help must return to canonical Home")


def validate_product_record(record: Mapping[str, Any]) -> dict[str, Any]:
    record_id, record_type = _validate_common_record(record)
    if record_type == "resource_item":
        _validate_resource_record(record)
    elif record_type == "enhancement_family":
        _validate_enhancement_record(record)
    elif record_type == "supply_depot":
        _validate_supply_record(record)
    elif record_type == "aggregate_daily_claim":
        _validate_aggregate_daily_claim_record(record)
    elif record_type == "activity_milestone_claim":
        _validate_activity_milestone_claim_record(record)
    elif record_type == "nova_praise":
        _validate_nova_praise_record(record)
    elif record_type == "ultimate_challenge":
        _validate_ultimate_challenge_record(record)
    elif record_type == "noahs_tavern_recruitment":
        _validate_noahs_tavern_recruitment_record(record)
    elif record_type == "troop_training":
        _validate_troop_training_record(record)
    elif record_type == "gathering_resources":
        _validate_gathering_resources_record(record)
    elif record_type == "zombie_lair":
        _validate_zombie_lair_record(record)
    elif record_type == "rare_earth_shop_purchase":
        _validate_rare_earth_shop_purchase_record(record)
    elif record_type == "hero_duel":
        _validate_hero_duel_record(record)
    elif record_type == "recommended_research":
        _validate_recommended_research_record(record)
    elif record_type == "food_farm_output_boost":
        _validate_food_farm_output_boost_record(record)
    elif record_type == "hall_of_war_zombie_zero":
        _validate_hall_of_war_zombie_zero_record(record)
    elif record_type == "hero_upgrade":
        _validate_hero_upgrade_record(record)
    elif record_type == "alliance_shop_purchase":
        _validate_alliance_shop_purchase_record(record)
    elif record_type == "alliance_donation":
        _validate_alliance_donation_record(record)
    elif record_type == "daily_shops_purchase":
        _validate_daily_shops_purchase_record(record)
    elif record_type == "ruins_shop_purchase":
        _validate_ruins_shop_purchase_record(record)
    elif record_type == "nanoweapon_normal_craft":
        _validate_nanoweapon_normal_craft_record(record)
    elif record_type == "nano_material_production":
        _validate_nano_material_production_record(record)
    elif record_type == "vip_points_popup_dismissal":
        _validate_vip_points_popup_dismissal_record(record)
    elif record_type == "world_map_navigation":
        _validate_world_map_navigation_record(record)
    elif record_type == "campaign_ap":
        _validate_campaign_ap_record(record)
    elif record_type == "ruins_challenge":
        _validate_ruins_challenge_record(record)
    elif record_type == "alliance_help":
        _validate_alliance_help_record(record)
    else:
        _validate_bioenhancer_research_record(record)
    return dict(record)


def _policy_ids(payload: Mapping[str, Any]) -> set[str]:
    policies = payload.get("policies")
    if not isinstance(policies, list) or not policies:
        raise ProductAuthorityError("product-policy registry requires policies")
    identities: set[str] = set()
    for policy in policies:
        if not isinstance(policy, Mapping):
            raise ProductAuthorityError("product-policy entry must be an object")
        identity = _require_nonempty_string(policy.get("policy_id"), "policy.policy_id")
        if identity in identities:
            raise ProductAuthorityError(f"duplicate policy_id: {identity}")
        identities.add(identity)
        for field in ("scope", "decision", "source"):
            _require_nonempty_string(policy.get(field), f"policy.{field}")
        if policy.get("status") not in POLICY_STATUSES:
            raise ProductAuthorityError(
                f"unknown product-policy status: {policy.get('status')}"
            )
    return identities



def _validate_d01_boundary_policies(payload: Mapping[str, Any]) -> None:
    """Keep REC-D01 safety and identity policy facts fail-closed offline."""

    policies = {
        policy["policy_id"]: policy
        for policy in payload["policies"]
        if isinstance(policy, Mapping)
    }

    def require_fields(policy_id: str, expected: Mapping[str, Any]) -> None:
        policy = policies.get(policy_id)
        if policy is None:
            raise ProductAuthorityError(f"missing REC-D01 policy: {policy_id}")
        for field, value in expected.items():
            if policy.get(field) != value:
                raise ProductAuthorityError(
                    f"REC-D01 policy {policy_id} has invalid {field}"
                )

    require_fields(
        "ultimate-daily-join-identity",
        {
            "daily_owner_task_id": "REC-D05",
            "daily_control": "Join",
            "main_control": "Clear",
            "campaign_ap_owner_task_id": "REC-R11",
            "catalog_admitted": False,
            "main_clear_is_daily": False,
            "campaign_ap_is_daily": False,
            "dispatch_authority": None,
        },
    )
    require_fields(
        "nova-personal-might-identity",
        {
            "nova_product_record_id": "nova_praise",
            "personal_might_catalog_key": "personal_might_praise",
            "distinct_identities": True,
            "personal_might_owner_task_id": "REC-D09",
            "nova_daily_owner_task_id": None,
            "dispatch_authority": None,
        },
    )
    require_fields(
        "buy-box-resource-boost-separation",
        {
            "buy_box_owner_task_id": "REC-P12",
            "resource_building_boost_owner_task_id": "REC-P10",
            "buy_box_catalog_key": "buy_box",
            "resource_building_boost_catalog_key": "boost_resource_building_output",
            "same_identity": False,
            "dispatch_authority": None,
        },
    )
    require_fields(
        "daily-control-cost-boundary",
        {
            "prohibited_controls": [
                "premium_purchase",
                "cash_purchase",
                "paid_control",
                "ambiguous_control",
                "refill",
                "10x",
                "item_backed_substitute",
            ],
            "premium_allowed": False,
            "cash_allowed": False,
            "paid_allowed": False,
            "ambiguous_allowed": False,
            "refill_allowed": False,
            "ten_x_allowed": False,
            "item_backed_substitute_allowed": False,
            "unknown_cost_allowed": False,
            "route_owned_effects_globally_forbidden": False,
            "route_owner_ticket_required": True,
            "governing_owner_ticket_families": ["REC-R*", "REC-P*"],
            "dispatch_authority": None,
        },
    )
    require_fields(
        "current-positive-completion-postcondition",
        {
            "applies_to": ["training", "march"],
            "current_positive_postcondition_required": True,
            "queue_projection_is_completion": False,
            "timer_projection_is_completion": False,
            "outbound_projection_is_completion": False,
            "return_projection_is_completion": False,
            "dispatch_is_completion": False,
        },
    )
    require_fields(
        "supply-depot-free-only",
        {
            "free_only": True,
            "stop_when_free_disappears": True,
            "permissions_infer_daily_completion": False,
            "daily_completion_requires_independent_positive_progress": True,
        },
    )
    unknown = policies.get("unknown-consequence")
    if (
        unknown is None
        or unknown.get("status") != "prohibited"
        or unknown.get("scope") != "global.unknown"
    ):
        raise ProductAuthorityError(
            "REC-D01 unknown cost controls must remain prohibited"
        )
    non_authorizing = payload.get("static_facts_are_non_authorizing")
    if non_authorizing != {
        "can_claim": False,
        "can_reserve": False,
        "can_enable": False,
        "can_dispatch": False,
        "runtime_authority": False,
    }:
        raise ProductAuthorityError(
            "REC-D01 static policy facts must be non-authorizing"
        )


def _validate_e_product_decision_policies(payload: Mapping[str, Any]) -> None:
    """Enforce the approved #75/#76/#78 decisions without granting runtime authority."""

    policies = {
        policy["policy_id"]: policy
        for policy in payload["policies"]
        if isinstance(policy, Mapping)
    }
    expected = {
        "hero-duel-policy": {
            "status": "explicitly_approved",
            "candidate_event": "hero_duel_survival",
            "daily_completion_target": 3,
            "maximum_confirmed_cycles_per_reset": 3,
            "hero_slots": 5,
            "pvp_entry_allowed": True,
            "defense_save_allowed": True,
            "attack_fill_missing_only": True,
            "combat_actions_allowed": False,
            "dispatch_authority": None,
        },
        "recommended-research-policy": {
            "status": "explicitly_approved",
            "first_displayed_recommendation_only": True,
            "maximum_starts_per_reset": 1,
            "queue1_idle_required": True,
            "queue2_activation_allowed": False,
            "ordinary_resources": ["food", "wood", "steel", "gas"],
            "exact_cost_and_balance_required": True,
            "shortage_behavior": "record_exact_shortages_and_defer",
            "dispatch_authority": None,
        },
        "food-farm-output-boost-policy": {
            "status": "explicitly_approved",
            "maximum_boosts_per_reset": 1,
            "resource_type": "FOOD",
            "owned_item_preferred": True,
            "inventory_count_must_be_independently_observed": True,
            "item_action_cost_is_not_inventory_count": True,
            "diamond_fallback_only_when_owned_item_count_is_zero": True,
            "current_offer_identity_duration_cost_balance_required": True,
            "diamond_fallback_offer": {
                "control": "Boost output (1-day)",
                "duration": "1-day",
                "currency": "DIAMONDS",
                "maximum_authorized_price_diamonds": 48,
                "current_numeric_price_must_be_observed": True,
                "current_numeric_price_must_not_exceed_authorized_cap": True,
                "current_balance_must_cover_exact_observed_price": True,
                "price_and_balance_rechecked_if_confirmation_appears": True,
            },
            "diamond_price_cap_not_assumed_current_price": True,
            "collection_effect_accounting_required": True,
            "buy_box_is_separate": True,
            "dispatch_authority": None,
        },
    }
    for policy_id, fields in expected.items():
        policy = policies.get(policy_id)
        if policy is None or any(policy.get(key) != value for key, value in fields.items()):
            raise ProductAuthorityError(
                f"approved product policy has invalid typed facts: {policy_id}"
            )



def _validate_f_product_decision_policies(payload: Mapping[str, Any]) -> None:
    """Enforce #95/#96/#67 saved-preset, minigame, and training decisions."""

    policies = {
        policy["policy_id"]: policy
        for policy in payload["policies"]
        if isinstance(policy, Mapping)
    }
    expected = {
        "commander-talent-preset-helper": {
            "status": "explicitly_approved",
            "saved_presets": ["Military", "Economy", "Training"],
            "existing_caller_owned_session_required": True,
            "standalone_route_or_scheduler_allowed": False,
            "exact_applied_state_required": True,
            "already_applied_redundant_switch_allowed": False,
            "cache_scope": "source_generation_and_runtime_context",
            "cache_invalidation_events": [
                "manual_or_external_change",
                "restart",
                "generation_change",
                "relevant_context_loss",
            ],
            "switch_requires_current_bound_control_and_cost_confirmation_cooldown": True,
            "switch_cost_allowance": "explicitly_observed_zero_cost_only",
            "route_approval_required": True,
            "changed_or_unknown_switch_facts": "defer",
            "positive_successor": "same_named_preset_row_applied",
            "uncertain_switch_retry_allowed": False,
            "talent_tree_edit_or_reset_allowed": False,
            "preset_creation_or_alteration_allowed": False,
            "dispatch_authority": None,
        },
        "hall-of-war-zombie-zero-policy": {
            "status": "explicitly_approved",
            "maximum_dispatches_per_reset": 1,
            "attempt_state_must_be_current": True,
            "busy_or_unavailable_attempt_must_not_dispatch": True,
            "dispatch_cost_allowance": "current_explicit_zero_only",
            "premium_or_refill_allowed": False,
            "current_troop_loss_effect_must_be_known_and_approved": True,
            "saved_commander_talent_preset": "Military",
            "saved_troop_set": "Troop Set 1",
            "maximum_reward_claims_per_reset": 1,
            "reward_requires_same_reset_positive_participation": True,
            "reward_requires_current_glowing_ready_row": True,
            "reward_claim_is_one_row_tap": True,
            "daily_quest_or_points_attribution_required": False,
            "dispatch_authority": None,
        },
        "troop-training-resource-policy": {
            "status": "explicitly_approved",
            "current_max_requires_current_numeric_maximum": True,
            "historical_numeric_maxima_are_not_policy": True,
            "resource_box_continuation": {
                "allowed_types": ["fighter", "vehicle"],
                "requires_exact_configured_training_context": True,
                "requires_current_recognized_resource_box_popup": True,
                "requires_observed_shortage_and_sufficient_post_box_balances": True,
                "warehouse_only_rejected": True,
                "effect_authority_required_before_consumption": True,
                "shooter_or_rider_allowed": False,
            },
            "scheduler_eligibility": False,
            "daily_quest_inheritance": "prohibited",
        },
    }
    for policy_id, fields in expected.items():
        policy = policies.get(policy_id)
        if policy is None or any(
            policy.get(key) != value for key, value in fields.items()
        ):
            raise ProductAuthorityError(
                f"approved F product policy has invalid typed facts: {policy_id}"
            )

def validate_daily_reset_policy(
    authority_or_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and return the exact typed static-UTC reset policy."""

    if not isinstance(authority_or_policy, Mapping):
        raise ProductAuthorityError("daily reset policy must be an object")
    if isinstance(authority_or_policy.get("policies"), list):
        matches = [
            policy
            for policy in authority_or_policy["policies"]
            if isinstance(policy, Mapping)
            and policy.get("policy_id") == DAILY_RESET_POLICY_ID
        ]
        if len(matches) != 1:
            raise ProductAuthorityError(
                "product authority must contain exactly one static UTC daily reset policy"
            )
        policy = matches[0]
    else:
        policy = authority_or_policy
    for field, expected in DAILY_RESET_POLICY_EXPECTED.items():
        if policy.get(field) != expected:
            raise ProductAuthorityError(
                f"daily reset policy field {field} is not the frozen static UTC value"
            )
    return dict(policy)

def _records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records = payload.get(PRODUCT_RECORDS_FIELD)
    if records is None:
        records = payload.get("representative_product_records")
    if not isinstance(records, list):
        raise ProductAuthorityError("product authority records must be a list")
    return records


def validate_product_authority(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate schema v2, typed policies, records, and digests."""

    if payload.get("schema_version") != AUTHORITY_SCHEMA_VERSION:
        raise ProductAuthorityError("unsupported product-policy schema")
    if payload.get("registry_kind") != AUTHORITY_REGISTRY_KIND:
        raise ProductAuthorityError("wrong product-policy registry kind")
    if payload.get("authority_revision") != AUTHORITY_REVISION:
        raise ProductAuthorityError("product authority revision is not the frozen revision")
    statuses = payload.get("status_vocabulary")
    if set(statuses or ()) != set(POLICY_STATUSES):
        raise ProductAuthorityError("product-policy vocabulary mismatch")
    _policy_ids(payload)
    validate_daily_reset_policy(payload)
    _validate_d01_boundary_policies(payload)
    _validate_e_product_decision_policies(payload)
    _validate_hero_upgrade_decision_policy(payload)
    _validate_f_product_decision_policies(payload)
    seen: set[str] = set()
    records_by_id: dict[str, Mapping[str, Any]] = {}
    for record in _records(payload):
        record_id = validate_product_record(record)["record_id"]
        if record_id in seen:
            raise ProductAuthorityError(f"duplicate product record: {record_id}")
        seen.add(record_id)
        records_by_id[record_id] = record
    if seen != set(RECORD_IDS):
        raise ProductAuthorityError("product authority record set is incomplete")
    aggregate = records_by_id["aggregate_daily_claim"]
    activity = records_by_id["activity_milestone_claim"]
    activity_binding = aggregate["additional_product_record_bindings"][0]
    if (
        activity_binding["product_record_revision"] != activity["record_revision"]
        or activity_binding["product_record_digest"] != activity["record_digest"]
    ):
        raise ProductAuthorityError(
            "aggregate Daily Claim references a stale Activity Milestone product record"
        )
    _require_sha256(payload.get("authority_digest"), "authority_digest")
    if payload["authority_digest"] != authority_digest(payload):
        raise ProductAuthorityError("stale product authority digest")
    return dict(payload)


def load_product_authority(path: Path = DEFAULT_AUTHORITY_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductAuthorityError(f"cannot load product authority: {path}") from exc
    return validate_product_authority(payload)


load_authority = load_product_authority


def get_daily_reset_policy(
    authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load or validate the exact static-UTC reset policy for Resource callers."""

    value = load_product_authority() if authority is None else authority
    validate_product_authority(value)
    return validate_daily_reset_policy(value)


def product_records_by_id(
    authority: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    validate_product_authority(authority)
    return {str(record["record_id"]): record for record in _records(authority)}


def _binding_from_contract(contract: Mapping[str, Any]) -> Mapping[str, Any] | None:
    primary = contract.get(CONTRACT_BINDING_FIELD)
    legacy_alias = contract.get("authority_binding")
    if primary is not None and legacy_alias is not None and primary != legacy_alias:
        raise ProductAuthorityError("contract contains conflicting authority bindings")
    binding = primary if primary is not None else legacy_alias
    if binding is None:
        return None
    if not isinstance(binding, Mapping):
        raise ProductAuthorityError("contract product authority binding must be an object")
    return binding


def _validate_direct_route_contract_content(contract: Mapping[str, Any]) -> None:
    """Reject selected-Daily prerequisites outside the binding metadata."""

    forbidden_tokens = (
        "selected_daily",
        "selected-daily",
        "selected daily",
        "daily_progress",
        "daily progress",
        "daily_quest",
        "daily quest",
        "quest_screen",
        "quest screen",
        "daily 5/5",
        "5/5",
    )

    def walk(value: Any, *, in_binding: bool = False) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                child_in_binding = in_binding or key in {
                    CONTRACT_BINDING_FIELD,
                    "authority_binding",
                }
                normalized_key = _normalized_field(key)
                if (
                    not child_in_binding
                    and normalized_key
                    in {"required_starting_context", "recognized_states"}
                    and isinstance(child, list)
                    and any(
                        isinstance(item, str)
                        and item.strip().casefold() == "home"
                        for item in child
                    )
                ):
                    raise ProductAuthorityError(
                        "direct-action contract cannot use generic Home authority"
                    )
                if (
                    not child_in_binding
                    and normalized_key
                    in {"from", "to", "start_state", "terminal_state"}
                    and isinstance(child, str)
                    and child.strip().casefold() == "home"
                ):
                    raise ProductAuthorityError(
                        "direct-action contract cannot use generic Home state"
                    )
                if normalized_key in {
                    "selected_daily",
                    "daily_progress",
                } or (
                    normalized_key == "selected_daily_prerequisite"
                    and child is not False
                ):
                    raise ProductAuthorityError(
                        "direct-action contract cannot require selected Daily state"
                    )
                walk(child, in_binding=child_in_binding)
        elif isinstance(value, list):
            for child in value:
                walk(child, in_binding=in_binding)
        elif isinstance(value, str):
            lowered = value.casefold()
            if any(token in lowered for token in forbidden_tokens):
                raise ProductAuthorityError(
                    "direct-action contract cannot depend on selected Daily state"
                )

    walk(contract)


def validate_contract_product_authority_binding(
    contract: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one optional schema-v2 representative contract binding.

    Contracts without the discriminator remain legacy/unmigrated and are
    intentionally accepted here.
    """

    binding = _binding_from_contract(contract)
    if binding is None:
        if contract.get("flow_id") == "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION":
            raise ProductAuthorityError(
                "Daily Claim contract requires an aggregate product-authority binding"
            )
        return dict(contract)
    validate_product_authority(authority)
    required = {
        "binding_type",
        "product_authority_revision",
        "product_authority_digest",
        "product_record_id",
        "product_record_revision",
        "product_record_digest",
        "platform",
        "platform_binding_ids",
        "home_authority",
        "terminal_home_authority",
    }
    missing = sorted(required - set(binding))
    if missing:
        raise ProductAuthorityError(
            f"contract authority binding missing fields: {', '.join(missing)}"
        )
    if binding["binding_type"] != "typed_product_record":
        raise ProductAuthorityError("unsupported contract authority binding discriminator")
    if binding["product_authority_revision"] != authority["authority_revision"]:
        raise ProductAuthorityError("contract references stale product authority revision")
    if binding["product_authority_digest"] != authority["authority_digest"]:
        raise ProductAuthorityError("contract references stale product authority digest")
    records = product_records_by_id(authority)
    record_id = binding["product_record_id"]
    if record_id not in records:
        raise ProductAuthorityError(f"contract references unknown product record: {record_id}")
    record = records[record_id]
    flow_id = contract.get("flow_id")
    if record_id == "aggregate_daily_claim" and flow_id != (
        "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"
    ):
        raise ProductAuthorityError(
            "aggregate Daily Claim record is reserved for the Daily Claim flow"
        )
    if record_id != "aggregate_daily_claim" and flow_id == (
        "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION"
    ):
        raise ProductAuthorityError(
            "Daily Claim flow must bind the aggregate Daily Claim record"
        )
    if binding.get("additional_product_record_bindings") is not None:
        raise ProductAuthorityError(
            "supplemental product records belong in the aggregate Daily Claim authority record"
        )
    if record_id == "ultimate_challenge" and flow_id != (
        "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
    ):
        raise ProductAuthorityError(
            "Ultimate Challenge record is reserved for the Ultimate Challenge flow"
        )
    if record_id != "ultimate_challenge" and flow_id == (
        "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION"
    ):
        raise ProductAuthorityError(
            "Ultimate Challenge flow must bind the Ultimate Challenge record"
        )
    if record_id == "activity_milestone_claim" and flow_id != (
        "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION"
    ):
        raise ProductAuthorityError(
            "Activity Milestone record is reserved for the Daily Milestone flow"
        )
    if record_id != "activity_milestone_claim" and flow_id == (
        "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION"
    ):
        raise ProductAuthorityError(
            "Daily Milestone flow must bind the Activity Milestone record"
        )
    if record_id == "campaign_ap" and contract.get(
        "flow_id"
    ) != "CAMPAIGN-AP-AUTO-BATTLE":
        raise ProductAuthorityError(
            "Campaign AP record is reserved for the Campaign AP Auto Battle flow"
        )
    if record_id != "campaign_ap" and contract.get(
        "flow_id"
    ) == "CAMPAIGN-AP-AUTO-BATTLE":
        raise ProductAuthorityError(
            "Campaign AP Auto Battle flow must bind the Campaign AP record"
        )
    if record_id == "troop_training" and contract.get(
        "flow_id"
    ) != "TROOP-TRAINING-END-TO-END-CONSOLIDATION":
        raise ProductAuthorityError(
            "Troop Training record is reserved for the Troop Training consolidation flow"
        )
    if record_id != "troop_training" and contract.get(
        "flow_id"
    ) == "TROOP-TRAINING-END-TO-END-CONSOLIDATION":
        raise ProductAuthorityError(
            "Troop Training consolidation flow must bind the Troop Training record"
        )
    if record_id == "gathering_resources" and contract.get(
        "flow_id"
    ) != "GATHERING-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "Gathering record is reserved for the Gathering flow"
        )
    if record_id != "gathering_resources" and contract.get(
        "flow_id"
    ) == "GATHERING-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "Gathering flow must bind the Gathering record"
        )
    if record_id == "zombie_lair" and contract.get(
        "flow_id"
    ) not in {
        "ZOMBIE-LAIR-BLUESTACKS-INTEGRATION",
        "ZOMBIE-LAIR-HOME-MAINTENANCE",
    }:
        raise ProductAuthorityError(
            "Zombie Lair record is reserved for Zombie Lair contracts"
        )
    if record_id != "zombie_lair" and contract.get(
        "flow_id"
    ) in {
        "ZOMBIE-LAIR-BLUESTACKS-INTEGRATION",
        "ZOMBIE-LAIR-HOME-MAINTENANCE",
    }:
        raise ProductAuthorityError(
            "Zombie Lair contracts must bind the Zombie Lair record"
        )
    if record_id == "nanoweapon_normal_craft" and contract.get(
        "flow_id"
    ) != "NANOWEAPON-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "Nanoweapon record is reserved for the Nanoweapon flow"
        )
    if record_id != "nanoweapon_normal_craft" and contract.get(
        "flow_id"
    ) == "NANOWEAPON-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "Nanoweapon flow must bind the Nanoweapon record"
        )
    if record_id == "nano_material_production" and contract.get(
        "flow_id"
    ) != "NANO-MATERIAL-PRODUCTION-MAINTENANCE":
        raise ProductAuthorityError(
            "Nano Material record is reserved for the Nano Material flow"
        )
    if record_id != "nano_material_production" and contract.get(
        "flow_id"
    ) == "NANO-MATERIAL-PRODUCTION-MAINTENANCE":
        raise ProductAuthorityError(
            "Nano Material flow must bind the Nano Material record"
        )
    if record_id == "world_map_navigation" and contract.get(
        "flow_id"
    ) != "WORLD-MAP-NAVIGATION-FOUNDATION":
        raise ProductAuthorityError(
            "World Map record is reserved for the World Map navigation flow"
        )
    if record_id != "world_map_navigation" and contract.get(
        "flow_id"
    ) == "WORLD-MAP-NAVIGATION-FOUNDATION":
        raise ProductAuthorityError(
            "World Map navigation flow must bind the World Map record"
        )
    if record_id == "vip_points_popup_dismissal" and contract.get(
        "flow_id"
    ) != "VIP-GET-PTS-POPUP-DISMISSAL":
        raise ProductAuthorityError(
            "VIP popup record is reserved for the VIP popup dismissal flow"
        )
    if record_id != "vip_points_popup_dismissal" and contract.get(
        "flow_id"
    ) == "VIP-GET-PTS-POPUP-DISMISSAL":
        raise ProductAuthorityError(
            "VIP popup dismissal flow must bind the VIP popup record"
        )
    if record_id == "ruins_challenge" and flow_id != (
        "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
    ):
        raise ProductAuthorityError("Ruins Challenge record is reserved for the Ruins route")
    if record_id != "ruins_challenge" and flow_id == (
        "RUINS-CHALLENGE-HOME-ATLAS-MIGRATION"
    ):
        raise ProductAuthorityError("Ruins route must bind the Ruins Challenge record")
    if record_id == "alliance_help" and flow_id != (
        "ALLIANCE-HELP-TEN-FREE-REQUESTS"
    ):
        raise ProductAuthorityError("Alliance Help record is reserved for the Help route")
    if record_id != "alliance_help" and flow_id == (
        "ALLIANCE-HELP-TEN-FREE-REQUESTS"
    ):
        raise ProductAuthorityError("Alliance Help route must bind the Alliance Help record")
    for reserved_id, reserved_flow in (
        ("hero_duel", "HERO-DUEL-EVIDENCE-GATE"),
        ("alliance_shop_purchase", "ALLIANCE-SHOP-PURCHASE-EVIDENCE-GATE"),
        ("alliance_donation", "ALLIANCE-TECH-DONATION-BLUESTACKS-INTEGRATION"),
        ("daily_shops_purchase", "DAILY-SHOPS-PURCHASE-EVIDENCE-GATE"),
        ("recommended_research", "RECOMMENDED-RESEARCH-BLUESTACKS-INTEGRATION"),
        ("food_farm_output_boost", "FOOD-FARM-OUTPUT-BOOST-DAILY-BLUESTACKS-INTEGRATION"),
        ("hall_of_war_zombie_zero", "HALL-OF-WAR-ZOMBIE-ZERO-BLUESTACKS-INTEGRATION"),
    ):
        if record_id == reserved_id and flow_id != reserved_flow:
            raise ProductAuthorityError(
                f"{reserved_id} record is reserved for {reserved_flow}"
            )
        if record_id != reserved_id and flow_id == reserved_flow:
            raise ProductAuthorityError(
                f"{reserved_flow} must bind the {reserved_id} record"
            )
    if binding["product_record_revision"] != record["record_revision"]:
        raise ProductAuthorityError("contract references stale product record revision")
    if binding["product_record_digest"] != record["record_digest"]:
        raise ProductAuthorityError("contract references stale product record digest")
    if binding["platform"] != BLUESTACKS_PLATFORM:
        raise ProductAuthorityError("representative contract must bind BlueStacks")
    ids = _require_string_list(binding["platform_binding_ids"], "platform_binding_ids")
    if set(ids) != set(EXPECTED_BLUESTACKS_BINDING_IDS) or len(ids) != len(
        EXPECTED_BLUESTACKS_BINDING_IDS
    ):
        raise ProductAuthorityError(
            "contract platform_binding_ids must equal the exact BlueStacks binding set"
        )
    if binding.get("platform_profile_id") != BLUESTACKS_PROFILE_ID:
        raise ProductAuthorityError("contract platform profile is not the native BlueStacks profile")
    if binding.get("package_id") != BLUESTACKS_PACKAGE_ID:
        raise ProductAuthorityError("contract package is not the P&S BlueStacks package")
    if "bliss" in json.dumps(binding, sort_keys=True).casefold():
        raise ProductAuthorityError("Bliss binding/evidence cannot satisfy BlueStacks")
    if binding["home_authority"] not in HOME_AUTHORITIES:
        raise ProductAuthorityError("contract Home authority must be a typed uppercase value")
    if binding["terminal_home_authority"] not in HOME_AUTHORITIES:
        raise ProductAuthorityError(
            "contract terminal Home authority must be a typed uppercase value"
        )
    route_sources = record["semantic_entry_route"]["source_home_authorities"]
    if binding["home_authority"] not in route_sources:
        raise ProductAuthorityError(
            "contract Home authority is not accepted by the bound product route"
        )
    if (
        binding["terminal_home_authority"]
        != record["terminal_requirement"]["home_authority"]
    ):
        raise ProductAuthorityError(
            "contract terminal Home authority does not match the product record"
        )
    accepted_home_authorities = binding.get("accepted_home_authorities")
    if accepted_home_authorities is not None:
        if (
            not isinstance(accepted_home_authorities, list)
            or accepted_home_authorities != list(route_sources)
        ):
            raise ProductAuthorityError(
                "contract accepted Home authorities do not match the product route"
            )
    for key in binding:
        if _normalized_field(key) in {
            "selected_daily",
            "selected_daily_prerequisite",
            "daily_progress",
        } and key != "selected_daily_prerequisite":
            raise ProductAuthorityError(
                "direct-action contract cannot contain selected Daily binding fields"
            )
    if binding.get("selected_daily_prerequisite", False) is not False:
        raise ProductAuthorityError(
            "representative direct-action contract cannot require selected Daily"
        )
    if record_id not in {"aggregate_daily_claim", "activity_milestone_claim"}:
        _validate_direct_route_contract_content(contract)
    elif record_id == "aggregate_daily_claim" and binding.get(
        "selected_daily_prerequisite"
    ) is not None:
        raise ProductAuthorityError(
            "aggregate Daily Claim binding must use product-record selected-Daily ownership"
        )
    return dict(contract)


def validate_contract_product_authority_bindings(
    authority: Mapping[str, Any],
    contracts: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]],
) -> None:
    """Validate every bound contract while leaving legacy contracts untouched."""

    if isinstance(contracts, Mapping):
        values = contracts.values()
    else:
        values = contracts
    for contract in values:
        if not isinstance(contract, Mapping):
            raise ProductAuthorityError("contract must be an object")
        validate_contract_product_authority_binding(contract, authority)


# Short aliases make the validation boundary convenient for focused callers.
validate_contract_binding = validate_contract_product_authority_binding
validate_contract_bindings = validate_contract_product_authority_bindings
validate_authority = validate_product_authority
