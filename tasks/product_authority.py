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
AUTHORITY_REVISION = "flow-delivery-product-authority-v2-r9"
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
    elif record_type != "noahs_tavern_recruitment" and (
        record["daily_ownership"].get("daily_owner") is not None
        or record[
        "daily_ownership"
        ].get("point_credit_trigger") is not None
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
    """Validate one typed representative record without mutating it."""

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
    if not isinstance(records, list) or len(records) != 10:
        raise ProductAuthorityError("product authority requires exactly ten records")
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
