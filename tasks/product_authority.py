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


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHORITY_PATH = REPO_ROOT / "tasks" / "flow_delivery_product_policy.json"
DEFAULT_POLICY_PATH = DEFAULT_AUTHORITY_PATH
AUTHORITY_SCHEMA_VERSION = 2
AUTHORITY_REGISTRY_KIND = "flow_delivery_product_policy"
AUTHORITY_REVISION = "flow-delivery-product-authority-v2-r11"
PRODUCT_AUTHORITY_SCHEMA_VERSION = AUTHORITY_SCHEMA_VERSION
PRODUCT_AUTHORITY_REVISION = AUTHORITY_REVISION
PRODUCT_RECORDS_FIELD = "product_records"
CONTRACT_BINDING_FIELD = "product_authority_binding"
BLUESTACKS_PLATFORM = "bluestacks"
BLUESTACKS_PROFILE_ID = "pns-bluestacks-5-p64-800x1280-v1"
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
        "rare_earth_shop_purchase",
        "nanoweapon_normal_craft",
        "nano_material_production",
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
        "rare_earth_shop_purchase",
        "nanoweapon_normal_craft",
        "nano_material_production",
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
        "rare_earth_shop_purchase": "RARE_EARTH_SHOP",
        "nanoweapon_normal_craft": "NANOWEAPON",
        "nano_material_production": "NANOWEAPON",
        "world_map_navigation": "WORLD",
    }[record_type]
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
        "rare_earth_shop_purchase": "rare_earth_shop_purchase",
        "nanoweapon_normal_craft": "nanoweapon_normal_craft",
        "nano_material_production": "nano_material_production",
        "world_map_navigation": "world_map_navigation",
    }[record_id]
    if record_type != expected_type:
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
    if effect.get("effect_ordinal") != 1:
        raise ProductAuthorityError("resource record effect ordinal must be one")
    forbidden = " ".join(str(item) for item in record.get("forbidden_actions", []))
    forbidden_lower = forbidden.casefold()
    if "daily navigation" not in forbidden_lower or "selected-daily" not in forbidden_lower:
        raise ProductAuthorityError(
            "resource record must forbid Daily navigation and selected-Daily prerequisites"
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
    """Validate the sole product record allowed to own selected Daily."""

    if record["objective"] != "aggregate_daily_claim":
        raise ProductAuthorityError(
            "aggregate Daily Claim record objective must be aggregate_daily_claim"
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
        target.get("kind") != "ordinary_daily_claim"
        or target.get("selected_daily") is not True
        or target.get("row_local") is not True
        or target.get("milestone") is not False
        or target.get("control") != "Claim"
    ):
        raise ProductAuthorityError(
            "aggregate Daily Claim must target one ordinary row-local Claim control"
        )
    quantity_cost = record.get("quantity_cost")
    if not isinstance(quantity_cost, Mapping) or quantity_cost.get("quantity") != 1:
        raise ProductAuthorityError(
            "aggregate Daily Claim quantity must be exactly one dispatch"
        )
    cost = quantity_cost.get("cost")
    if not isinstance(cost, Mapping) or (
        cost.get("kind") != "zero_cost_claim"
        or cost.get("amount") != 0
        or cost.get("unit") != "Claim"
        or cost.get("free_only") is not True
    ):
        raise ProductAuthorityError("aggregate Daily Claim must be free and zero-cost")
    effect = record["semantic_effect"]
    if (
        effect.get("effect_ordinal") != 1
        or effect.get("positive_points_delta_required") is not True
        or effect.get("ordinary_claim_controls_cleared_required") is not True
        or effect.get("dispatch_is_not_success_proof") is not True
    ):
        raise ProductAuthorityError(
            "aggregate Daily Claim requires one dispatch and positive points/control successor"
        )
    ownership = record["daily_ownership"]
    if ownership.get("daily_owner") != "aggregate_daily_claim" or ownership.get(
        "point_credit_trigger"
    ) != "positive_points_delta_and_ordinary_claim_controls_cleared":
        raise ProductAuthorityError(
            "aggregate Daily Claim ownership and point trigger are incomplete"
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
    ):
        if marker not in forbidden_lower:
            raise ProductAuthorityError(
                f"aggregate Daily Claim must forbid {marker} controls"
            )


def _validate_activity_milestone_claim_record(record: Mapping[str, Any]) -> None:
    """Validate one reset-bound, zero-cost Activity Milestone chest claim."""

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
        or target.get("eligibility") != "one_current_ready_free_milestone_per_reset"
        or target.get("panel") != "ACTIVITY_MILESTONES"
        or target.get("control") != "MILESTONE_CHEST"
        or target.get("quantity") != 1
        or target.get("reset_bound") is not True
        or target.get("fully_visible") is not True
    ):
        raise ProductAuthorityError(
            "Activity Milestone target must bind one current, ready, fully visible free chest"
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
        or effect.get("positive_bound_points_successor_allowed") is not True
        or effect.get("dispatch_is_not_success_proof") is not True
        or effect.get("success_requires")
        != "same_milestone_opened_or_positive_bound_points_successor"
        or effect.get("terminal_home_separate") is not True
        or effect.get("identical_retry") is not False
    ):
        raise ProductAuthorityError(
            "Activity Milestone must require same-milestone successor, separate dispatch and terminal proof, and retry denial"
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
    if record["recurrence"] != "evidence_gated_variant_canary":
        raise ProductAuthorityError(
            "Gathering recurrence must be evidence_gated_variant_canary"
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
        or target.get("source_daily_row_required") is not True
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
    """Validate one exact once-per-reset Normal Craft Nanoweapon action."""

    if record["objective"] != "nanoweapon_daily_craft":
        raise ProductAuthorityError(
            "Nanoweapon record objective must be nanoweapon_daily_craft"
        )
    if record["action"] != "start_one_normal_nanoweapon_craft":
        raise ProductAuthorityError(
            "Nanoweapon action must be start_one_normal_nanoweapon_craft"
        )
    if record["recurrence"] != "daily_reset_scoped":
        raise ProductAuthorityError(
            "Nanoweapon recurrence must be daily_reset_scoped"
        )
    route = record["semantic_entry_route"]
    if (
        route.get("source_home_authorities") != ["HOME_CANONICAL"]
        or route.get("route")
        != ["GEAR_FACTORY", "NANOWEAPON", "NORMAL_CRAFT"]
    ):
        raise ProductAuthorityError(
            "Nanoweapon entry route must bind canonical Home to Normal Craft"
        )
    target = record["target"]
    if (
        target.get("kind") != "nanoweapon_normal_craft"
        or target.get("craft_mode") != "NORMAL_CRAFT"
        or target.get("completed_claim_on_entry") is not True
        or target.get("parts_required") != 100
        or target.get("parts_unit") != "NANO_PARTS"
        or target.get("maximum_active_crafts") != 1
        or target.get("maximum_starts_per_reset") != 1
        or target.get("craft_duration_seconds") != 43200
        or target.get("exclusive_craft_allowed") is not False
        or target.get("rotating_display_selection_allowed") is not False
        or target.get("insufficient_parts_defer") is not True
        or target.get("disabled_craft_defer") is not True
        or target.get("terminal_home") != "HOME_CANONICAL"
    ):
        raise ProductAuthorityError(
            "Nanoweapon target must bind one exact 100-part Normal Craft"
        )
    quantity_cost = record["quantity_cost"]
    cost = quantity_cost.get("cost")
    if (
        quantity_cost.get("quantity") != 1
        or not isinstance(cost, Mapping)
        or cost.get("kind") != "exact_material"
        or cost.get("amount") != 100
        or cost.get("unit") != "NANO_PARTS"
        or cost.get("free_only") is not False
    ):
        raise ProductAuthorityError(
            "Nanoweapon must bind exact 100 NANO_PARTS consumption"
        )
    effect = record["semantic_effect"]
    required_effects = (
        "completed_claim_successor_required",
        "exact_parts_consumption_required",
        "single_active_craft_required",
        "single_start_per_reset_required",
        "exact_duration_required",
        "craft_successor_required",
        "daily_objective_successor_required",
        "no_currency_box_or_item_input",
        "dispatch_is_not_success_proof",
    )
    if (
        effect.get("effect_ordinal") != 1
        or any(effect.get(field) is not True for field in required_effects)
        or effect.get("daily_ownership") != "none"
        or effect.get("identical_retry") is not False
    ):
        raise ProductAuthorityError(
            "Nanoweapon successor, cost, or retry safety effect is incomplete"
        )
    terminal = record["terminal_requirement"]
    if terminal.get("home_authority") != "HOME_CANONICAL" or terminal.get(
        "return_required"
    ) is not True:
        raise ProductAuthorityError(
            "Nanoweapon terminal requirement must return to canonical Home"
        )
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "material production",
        "inherit",
        "exclusive craft",
        "rotating weapon display",
        "insufficient nano parts",
        "disabled craft",
        "multiple active",
        "second craft",
        "currency",
        "resource box",
        "item",
        "identical retry",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(
                f"Nanoweapon forbidden actions must include {marker}"
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
    forbidden = json.dumps(record["forbidden_actions"], sort_keys=True).casefold()
    for marker in (
        "base resource",
        "resource box",
        "currency",
        "item",
        "normal craft",
        "exclusive craft",
        "multiple active",
        "wrong duration",
        "unknown production",
        "identical retry",
    ):
        if marker not in forbidden:
            raise ProductAuthorityError(
                f"Nano Material forbidden actions must include {marker}"
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
    elif record_type == "ruins_shop_purchase":
        _validate_ruins_shop_purchase_record(record)
    elif record_type == "nanoweapon_normal_craft":
        _validate_nanoweapon_normal_craft_record(record)
    elif record_type == "nano_material_production":
        _validate_nano_material_production_record(record)
    elif record_type == "world_map_navigation":
        _validate_world_map_navigation_record(record)
    elif record_type == "campaign_ap":
        _validate_campaign_ap_record(record)
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
    if not isinstance(records, list) or len(records) != 18:
        raise ProductAuthorityError("product authority requires exactly eighteen records")
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
    records = _records(payload)
    seen: set[str] = set()
    for record in records:
        record_id = validate_product_record(record)["record_id"]
        if record_id in seen:
            raise ProductAuthorityError(f"duplicate product record: {record_id}")
        seen.add(record_id)
    if seen != set(RECORD_IDS):
        raise ProductAuthorityError("product authority record set is incomplete")
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
    if record_id == "aggregate_daily_claim" and contract.get(
        "flow_id"
    ) != "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "aggregate Daily Claim record is reserved for the Daily Claim flow"
        )
    if record_id != "aggregate_daily_claim" and contract.get(
        "flow_id"
    ) == "DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "Daily Claim flow must bind the aggregate Daily Claim record"
        )
    if record_id == "ultimate_challenge" and contract.get(
        "flow_id"
    ) != "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "Ultimate Challenge record is reserved for the Ultimate Challenge flow"
        )
    if record_id != "ultimate_challenge" and contract.get(
        "flow_id"
    ) == "ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "Ultimate Challenge flow must bind the Ultimate Challenge record"
        )
    if record_id == "activity_milestone_claim" and contract.get(
        "flow_id"
    ) != "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "Activity Milestone record is reserved for the Daily Milestone flow"
        )
    if record_id != "activity_milestone_claim" and contract.get(
        "flow_id"
    ) == "DAILY-MILESTONE-CLAIM-BLUESTACKS-INTEGRATION":
        raise ProductAuthorityError(
            "Daily Milestone flow must bind the Activity Milestone record"
        )
    if record_id == "campaign_ap" and contract.get(
        "flow_id"
    ) != "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY":
        raise ProductAuthorityError(
            "Campaign AP record is reserved for the Campaign AP Auto Battle flow"
        )
    if record_id != "campaign_ap" and contract.get(
        "flow_id"
    ) == "CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY":
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
