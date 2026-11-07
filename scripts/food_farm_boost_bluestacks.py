"""Bounded native Food Farm boost route; route effects stay in the canonical action store."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safe_action_core import ActionClass, ActionStatus, CentralPolicy, Observation, PolicyRequest, SafeActionExecutor, TransportResult
from scripts.bounded_tesseract import call_ocr, tesseract_data
from scripts.startup_normalization import is_clean_home_frame
from tasks.home_atlas import load_home_atlas
from tasks.home_atlas_vision import BLUESTACKS_SAFE_INTERACTION_BOX, HUD_MASK_RECTS, BlueStacksHomeLocalizer, bind_visible_building, frame_digest
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID
from tasks.resource_boost_disabled import (
    FOOD_FARM_RESOURCE_TYPES,
    FoodFarmBoostChoice,
    FoodFarmBoostObservation,
    food_farm_boost_daily_action_key,
    food_farm_boost_decision,
    food_farm_boost_postcondition_verified,
    food_farm_canonical_action_state,
    food_farm_collection_effect,
)

FLOW_ID = "FOOD-FARM-OUTPUT-BOOST-DAILY-BLUESTACKS-INTEGRATION"
PRODUCT_ID = "food_farm_output_boost"
PRODUCT_REVISION = "food_farm_output_boost-v1"
MAX_INPUTS = 16
MAX_ACTIONS = 2
ONE_DAY_SECONDS = 86_400
DEFAULT_ATLAS = ROOT / "tasks" / "assets" / "home_atlas" / "bluestacks" / "800x1280" / "atlas.json"
_FARM_ID = re.compile(r"^home\.building\.farm\.\d{2}$")
_PLAIN_COUNT = re.compile(r"^[0-9][0-9,]*$")
_TIMER = re.compile(r"\bboosting\s*(\d{1,2}):(\d{2}):(\d{2})\b", re.IGNORECASE)
_DURATION = re.compile(r"boost\s+output\s*\(?\s*(\d+)\s*[- ]?(day|days|hour|hours|hr|hrs|min|mins)\b", re.IGNORECASE)


@dataclass(frozen=True)
class NativeTextToken:
    text: str
    confidence: float
    roi: tuple[int, int, int, int]


@dataclass(frozen=True)
class FarmBinding:
    building_id: str
    target_roi: tuple[int, int, int, int]
    frame_sha256: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class BoostPanelRead:
    observation: FoodFarmBoostObservation
    item_control_roi: tuple[int, int, int, int] | None
    diamond_control_roi: tuple[int, int, int, int] | None
    confirmation_control_roi: tuple[int, int, int, int] | None
    text: str
    balances: Mapping[str, int | None]

    source_capture: Any

def _ocr_tokens(frame: np.ndarray) -> tuple[NativeTextToken, ...]:
    if frame.ndim != 3 or frame.size == 0:
        return ()
    try:
        data = call_ocr(tesseract_data, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), config="--psm 11")
    except Exception:
        return ()
    texts = data.get("text", ())
    tokens: list[NativeTextToken] = []
    for i, raw in enumerate(texts):
        text = " ".join(str(raw or "").split())
        confidence_raw = str(data.get("conf", [])[i]) if i < len(data.get("conf", ())) else "-1"
        try:
            confidence = float(confidence_raw)
            x, y, width, height = (int(data[k][i]) for k in ("left", "top", "width", "height"))
        except (TypeError, ValueError, IndexError):
            continue
        if text and confidence >= 50 and width > 0 and height > 0:
            tokens.append(NativeTextToken(text, confidence, (x, y, x + width, y + height)))
    return tuple(tokens)


def _token_text(tokens: tuple[NativeTextToken, ...]) -> str:
    return " ".join(token.text for token in tokens)


def _exact_balance(text: str) -> int | None:
    normalized = text.replace(" ", "")
    if not _PLAIN_COUNT.fullmatch(normalized):
        return None
    try:
        return int(normalized.replace(",", ""))
    except ValueError:
        return None



def _row_roi(tokens: tuple[NativeTextToken, ...], *, x0: int, x1: int, y0: int, y1: int) -> tuple[int, int, int, int] | None:
    selected = [
        token for token in tokens
        if x0 <= (token.roi[0] + token.roi[2]) // 2 < x1
        and y0 <= (token.roi[1] + token.roi[3]) // 2 < y1
    ]
    words = " ".join(token.text.casefold() for token in selected)
    if "boost" not in words or "output" not in words:
        return None
    x_min = min(token.roi[0] for token in selected)
    y_min = min(token.roi[1] for token in selected)
    x_max = max(token.roi[2] for token in selected)
    y_max = max(token.roi[3] for token in selected)
    return max(0, x_min - 18), max(0, y_min - 18), min(800, x_max + 18), min(1280, y_max + 18)
def _row_text(tokens: tuple[NativeTextToken, ...], roi: tuple[int, int, int, int] | None) -> str | None:
    if roi is None:
        return None
    x0, y0, x1, y1 = roi
    selected = [
        token for token in tokens
        if x0 <= (token.roi[0] + token.roi[2]) // 2 < x1
        and y0 <= (token.roi[1] + token.roi[3]) // 2 < y1
    ]
    if not selected:
        return None
    text = " ".join(token.text for token in selected).strip()
    return text or None


def _row_action_cost(tokens: tuple[NativeTextToken, ...], roi: tuple[int, int, int, int] | None) -> int | None:
    if roi is None:
        return None
    x0, y0, x1, y1 = roi
    row = [
        token for token in tokens
        if x0 <= (token.roi[0] + token.roi[2]) // 2 < x1
        and y0 <= (token.roi[1] + token.roi[3]) // 2 < y1
    ]
    costs = []
    for index, token in enumerate(row):
        text = token.text.casefold().replace(" ", "")
        if text in {"x1", "×1"}:
            costs.append(1)
        elif text in {"x", "×"} and index + 1 < len(row):
            following = row[index + 1]
            if following.text.strip() == "1" and abs(following.roi[1] - token.roi[1]) <= 20:
                costs.append(1)
    return costs[0] if len(costs) == 1 else None


def _item_subject(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def _duration_seconds(value: str | None) -> int | None:
    if not isinstance(value, str):
        return None
    match = _DURATION.search(" ".join(value.casefold().split()))
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    factor = 86400 if unit.startswith("day") else 3600 if unit.startswith(("hour", "hr")) else 60
    return amount * factor if amount > 0 else None


def _json_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _prior_boost_confirmation_matches(row: Mapping[str, Any], farm_id: str) -> bool:
    proof = _json_mapping(row.get("reconciliation_result_json"))
    request = _json_mapping(row.get("policy_request_json"))
    preconditions = request.get("semantic_preconditions")
    return bool(
        row.get("target_identity") == farm_id
        and row.get("expected_postcondition") == "FOOD_FARM_POSITIVE_BOOSTING_TIMER"
        and row.get("consequence") == "consume_one_exact_named_owned_food_farm_output_boost_item"
        and isinstance(preconditions, (tuple, list))
        and f"exact_current_food_farm_item_duration_seconds:{ONE_DAY_SECONDS}" in preconditions
        and any(
            isinstance(item, str) and item.startswith("exact_current_food_farm_item_name:")
            and item.split(":", 1)[1].strip()
            for item in preconditions
        )
        and proof.get("confirmed") is True
        and isinstance(proof.get("frame_sha256"), str)
        and re.fullmatch(r"[a-f0-9]{64}", proof["frame_sha256"]) is not None
    )


def _has_blue_diamond_before(frame: np.ndarray, token: NativeTextToken) -> bool:
    x0, y0, _x1, y1 = token.roi
    left = max(0, x0 - 42)
    top = max(0, y0 - 12)
    right = max(left + 1, x0 - 3)
    bottom = min(frame.shape[0], y1 + 12)
    if right <= left or bottom <= top:
        return False
    hsv = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array((85, 70, 60), np.uint8), np.array((135, 255, 255), np.uint8))
    return int(cv2.countNonZero(blue)) >= 8

def observe_home_resource_balances(frame: np.ndarray) -> dict[str, int | None]:
    """Read only exact, non-abbreviated values from the current Home resource bar."""
    tokens = _ocr_tokens(frame)
    # The four fixed HUD columns are screen-layout anchors, not building tap coordinates.
    columns = ((0, 140), (140, 280), (280, 420), (420, 560))
    result: dict[str, int | None] = {}
    for resource, (left, right) in zip(("FOOD", "WOOD", "STEEL", "GAS"), columns):
        matches = [
            token for token in tokens
            if left <= (token.roi[0] + token.roi[2]) // 2 < right
            and token.roi[1] < 100
            and _exact_balance(token.text) is not None
        ]
        result[resource] = _exact_balance(matches[0].text) if len(matches) == 1 else None
    return result


def _farm_ids(atlas) -> tuple[str, ...]:
    return tuple(sorted(
        building.semantic_id for building in atlas.buildings
        if _FARM_ID.fullmatch(building.semantic_id)
    ))


def _binding_is_interactable(binding, frame: np.ndarray) -> bool:
    if binding is None or binding.frame_sha256 != frame_digest(frame):
        return False
    try:
        x0, y0, x1, y1 = binding.target_roi
    except (TypeError, ValueError):
        return False
    sx0, sy0, sx1, sy1 = BLUESTACKS_SAFE_INTERACTION_BOX
    return bool(
        sx0 <= x0 < x1 <= sx1 and sy0 <= y0 < y1 <= sy1
        and not binding.overlay_intersects and not binding.ambiguous_overlap
        and binding.semantic_evidence
        and not any(x0 < hx1 and x1 > hx0 and y0 < hy1 and y1 > hy0
                    for hx0, hy0, hx1, hy1 in HUD_MASK_RECTS)
    )


def bind_reachable_farm(
    frame: np.ndarray, atlas, localizer: BlueStacksHomeLocalizer, *, localization=None,
) -> FarmBinding | None:
    """Choose any fresh visible mapped Farm whose bound hit region is safe."""
    if not is_clean_home_frame(frame):
        return None
    current_localization = localization if localization is not None else localizer.localize(frame)
    if not current_localization.recognized or current_localization.stale or current_localization.overlay:
        return None
    candidates = []
    for building_id in _farm_ids(atlas):
        binding = bind_visible_building(
            frame, current_localization, atlas.lookup_building(building_id),
            home_is_clean=is_clean_home_frame,
        )
        if _binding_is_interactable(binding, frame):
            candidates.append((building_id, binding))
    if not candidates:
        return None
    building_id, binding = candidates[0]
    return FarmBinding(
        building_id=building_id,
        target_roi=tuple(int(value) for value in binding.target_roi),
        frame_sha256=frame_digest(frame),
        evidence=tuple(str(value) for value in binding.semantic_evidence),
    )



def _food_farm_observation(
    *,
    farm_identity: str,
    active_remaining_seconds: int | None,
    option_duration_seconds: int | None,
    option_item_name: str | None,
    option_item_cost: int | None,
    option_item_visible: bool,
    inventory_item_name: str | None,
    inventory_item_count: int | None,
    inventory_observed: bool,
    diamond_option_visible: bool,
    diamond_item_name: str | None,
    diamond_duration_seconds: int | None,
    diamond_cost: int | None,
    diamond_balance: int | None,
    diamond_direct_action_observed: bool,
    overlay_state: str,
    source_frame_sha256: str,
    evidence_refs: tuple[str, ...],
    runtime_profile_id: str,
) -> FoodFarmBoostObservation:
    """Adapt only current panel evidence; unknown inventory/direct semantics stay unknown."""
    active = type(active_remaining_seconds) is int and active_remaining_seconds > 0
    exact_inventory = bool(
        inventory_observed and isinstance(inventory_item_name, str) and inventory_item_name.strip()
        and type(inventory_item_count) is int and inventory_item_count >= 0
    )
    exact_direct_offer = bool(
        diamond_direct_action_observed and diamond_option_visible
        and isinstance(diamond_item_name, str) and diamond_item_name.strip()
        and type(diamond_duration_seconds) is int and diamond_duration_seconds > 0
        and type(diamond_cost) is int and diamond_cost > 0
        and type(diamond_balance) is int and diamond_balance >= diamond_cost
    )
    return FoodFarmBoostObservation(
        screen_state="FOOD_FARM_ACTIVE_BOOST" if active else "FOOD_FARM_BOOST_PANEL",
        farm_identity=farm_identity,
        resource_type="FOOD",
        boost_active=active,
        active_remaining_seconds=active_remaining_seconds if active else None,
        option_duration_seconds=option_duration_seconds,
        option_item_name=option_item_name,
        option_item_cost=option_item_cost,
        option_item_visible=option_item_visible,
        inventory_item_name=inventory_item_name if exact_inventory else None,
        inventory_item_count=inventory_item_count if exact_inventory else None,
        inventory_observed=exact_inventory,
        diamond_option_visible=diamond_option_visible,
        diamond_item_name=diamond_item_name,
        diamond_duration_seconds=diamond_duration_seconds,
        diamond_cost=diamond_cost,
        diamond_balance=diamond_balance,
        diamond_offer_actionable=exact_direct_offer,
        overlay_state=overlay_state,
        source_frame_sha256=source_frame_sha256,
        evidence_refs=evidence_refs,
        runtime_profile_id=runtime_profile_id,
        recognized=True,
        boost_options_visible=not active and (option_item_visible or diamond_option_visible),
    )


def observe_food_farm_boost_panel(
    captured,
    *,
    farm_identity: str,
    runtime_profile_id: str = ACTIVE_RUNTIME_PROFILE_ID,
    evidence_ref: str,
) -> BoostPanelRead | None:
    """Recognize only the exact visible Farm Boost surface; unproven inventory stays unknown."""
    tokens = _ocr_tokens(captured.frame)
    text = _token_text(tokens)
    folded = " ".join(text.casefold().split())
    if not _FARM_ID.fullmatch(farm_identity) or "boost" not in folded or "food output" not in folded or "food cap" not in folded:
        return None
    timer = _TIMER.search(folded)
    active_seconds = None
    if timer is not None:
        hours, minutes, seconds = map(int, timer.groups())
        if minutes < 60 and seconds < 60:
            active_seconds = hours * 3600 + minutes * 60 + seconds
    balance_tokens = [
        token for token in tokens
        if 560 <= (token.roi[0] + token.roi[2]) // 2 < 720 and token.roi[1] < 100
    ]
    height, width = captured.frame.shape[:2]
    option_band = (max(0, height - 230), max(0, height - 25))
    diamond_roi = _row_roi(tokens, x0=40, x1=width // 2, y0=option_band[0], y1=option_band[1])
    item_roi = _row_roi(tokens, x0=width // 2, x1=width - 40, y0=option_band[0], y1=option_band[1])
    diamond_counts = [
        (token, _exact_balance(token.text)) for token in tokens
        if token.roi[1] >= option_band[0] and token.roi[2] <= width // 2
        and _exact_balance(token.text) is not None and _has_blue_diamond_before(captured.frame, token)
    ]
    diamond_cost = diamond_counts[0][1] if len(diamond_counts) == 1 else None
    item_cost = _row_action_cost(tokens, item_roi)
    option_name = _row_text(tokens, item_roi)
    diamond_name = _row_text(tokens, diamond_roi)
    option_duration_seconds = _duration_seconds(option_name)
    diamond_duration_seconds = _duration_seconds(diamond_name)
    diamond_balance = _exact_balance(balance_tokens[0].text) if len(balance_tokens) == 1 else None
    observation = _food_farm_observation(
        farm_identity=farm_identity,
        active_remaining_seconds=active_seconds,
        option_duration_seconds=option_duration_seconds,
        option_item_name=option_name,
        option_item_cost=item_cost,
        option_item_visible=item_roi is not None,
        inventory_item_name=None,
        inventory_item_count=None,
        inventory_observed=False,
        diamond_option_visible=diamond_roi is not None and diamond_cost is not None,
        diamond_item_name=diamond_name,
        diamond_duration_seconds=diamond_duration_seconds,
        diamond_cost=diamond_cost,
        diamond_balance=diamond_balance,
        diamond_direct_action_observed=False,
        overlay_state="none" if not _generic_overlay(frame=captured.frame) else "unknown",
        source_frame_sha256=str(captured.sha256),
        evidence_refs=(evidence_ref,),
        runtime_profile_id=runtime_profile_id,
    )
    return BoostPanelRead(
        observation, item_roi, diamond_roi, None, text,
        observe_home_resource_balances(captured.frame), captured,
    )


def _generic_overlay(frame: np.ndarray) -> bool:
    # Only a positive Home/boost OCR result is meaningful here. The shared startup
    # recovery owns any modal; an unclassified visual panel is never dismissed.
    return not is_clean_home_frame(frame) and not _visible_food_farm_boost_text(frame)


def _visible_food_farm_boost_text(frame: np.ndarray) -> bool:
    text = _token_text(_ocr_tokens(frame)).casefold()
    return "boost" in text and "food output" in text and "food cap" in text


def _evidence_ref(captured, session) -> str:
    try:
        relative = Path(captured.path).resolve().relative_to(Path(session.session_directory).resolve())
        return "evidence/" + relative.as_posix()
    except (OSError, ValueError):
        return ""


def _identity_value(identity, field: str) -> str:
    value = getattr(identity, field, None)
    if type(value) is not str or not value:
        raise ValueError(f"Food Farm requires a verified {field}")
    return value


def _route_observation(captured, *, context, binding: FarmBinding, source_state: str, control_class: str,
                       consequence: str, postcondition: str, resource_type: str = "none",
                       cost_amount: float = 0, quantity: int = 1, runtime_profile_id: str) -> Observation:
    try:
        package = str(context.runtime.measure_foreground_package())
    except Exception:
        package = ""
    return Observation(
        frame_sha256=str(captured.sha256),
        capture_completed_monotonic=float(captured.captured_monotonic),
        runtime_profile_id=runtime_profile_id,
        width=int(captured.frame.shape[1]), height=int(captured.frame.shape[0]),
        valid_png=True, corrupt=False, black=False, source_state=source_state,
        overlay_state="none_observed", target_identity=binding.building_id,
        target_roi=binding.target_roi, recognized=True, control_class=control_class,
        consequence=consequence, cost_type=resource_type, cost_amount=cost_amount,
        quantity=quantity, expected_postcondition=postcondition,
        evidence_refs=(str(captured.path),), source_family="food_farm_boost",
        target_isolated=True, package_foreground=package == "com.global.ztmslg",
    )


def _dispatch_canonical_action(
    *, context, binding: FarmBinding, source_capture, target_roi: tuple[int, int, int, int],
    action_key: str, action_kind: str, source_state: str, control_class: str,
    consequence: str, postcondition: str, action_class: ActionClass, cost_type: str,
    cost_amount: float, maximum_cost: float, subject: str, semantic_preconditions: tuple[str, ...],
    after_observer, runtime_profile_id: str,
) -> dict[str, Any]:
    runtime, store, session = context.runtime, context.action_store, context.session
    task_id = FLOW_ID
    action_id = f"food-farm:{hashlib.sha256((action_key + session.invocation_id).encode()).hexdigest()}"
    immediate_capture = source_capture
    if immediate_capture.sha256 != binding.frame_sha256:
        return {"status": "blocked", "reason": "FOOD_FARM_TARGET_REBIND_REQUIRED", "transport_calls": 0}
    observation = _route_observation(
        immediate_capture, context=context, binding=binding, source_state=source_state,
        control_class=control_class, consequence=consequence, postcondition=postcondition,
        resource_type=cost_type, cost_amount=cost_amount, quantity=1,
        runtime_profile_id=runtime_profile_id,
    )
    if observation.target_roi != target_roi:
        return {"status": "blocked", "reason": "FOOD_FARM_TARGET_ROI_CHANGED", "transport_calls": 0}
    now = float(context.utc_clock()) if callable(getattr(context, "utc_clock", None)) else time.time()
    monotonic_now = float(context.monotonic_clock()) if callable(getattr(context, "monotonic_clock", None)) else time.monotonic()
    request = PolicyRequest(
        action_id=action_id, action_key=action_key, task_id=task_id,
        task_mode="supervised_validation", semantic_action=action_kind,
        expected_runtime_profile_id=runtime_profile_id, observation=observation,
        monotonic_now=monotonic_now, observation_max_age_seconds=30.0,
        dispatch_max_age_seconds=30.0, lease_owner=session.owner,
        lease_valid=store.lease_valid_for(session.owner, now),
        unresolved_action=store.has_action_block(), duplicate_action_key=store.action_key_exists(action_key),
        game_day_id=_identity_value(context.identity, "reset_id"), action_class=action_class,
        action_kind=action_kind, subject=subject, resource_or_currency=cost_type,
        maximum_cost=maximum_cost, free_only=cost_amount == 0,
        semantic_preconditions=semantic_preconditions,
        semantic_postconditions=(postcondition,), runtime_session_id=str(runtime.session),
    )
    policy = CentralPolicy(frozenset({task_id}))
    issued = policy.issue_capability(request)
    store.audit(task_id, "capability_issued", now, issued.audit, action_id)
    if not issued.authorized or issued.capability is None:
        return {"status": "blocked", "reason": issued.reason_code, "transport_calls": 0}

    post_captures = []
    post_values = {}

    def transport(_intent):
        starting_count = int(getattr(runtime, "input_count", 0))

        def authorize(before):
            if before.sha256 != immediate_capture.sha256:
                raise RuntimeError("Food Farm consequential target frame changed before input")
            context.checkpoint()
            context.validate_identity()

        def dispatch(before):
            runtime.tap(
                before, target_identity=binding.building_id, target_roi=target_roi,
                action_key=action_key, action_class=action_kind, consequential=True,
            )

        def recognize(after):
            semantic = bool(after_observer(after))
            post_captures.append(after)
            post_values[str(after.path)] = semantic
            return postcondition if semantic else "unknown"

        def settled_successor():
            time.sleep(float(getattr(context, "settle_seconds", 1.0)))
            context.checkpoint()
            return runtime.capture("food-farm-action-successor-settled")

        try:
            session.run_action(
                action_class=action_kind, label=f"food-farm-{action_kind}",
                capture=runtime.capture, authorize=authorize, dispatch=dispatch,
                recognize=recognize, settled_successor=settled_successor,
                consequence_class=consequence,
            )
        except Exception as exc:
            sent = int(getattr(runtime, "input_count", 0)) - starting_count
            return TransportResult(sent == 1, f"FOOD_FARM_SESSION_ACTION_{type(exc).__name__}")
        sent = int(getattr(runtime, "input_count", 0)) - starting_count
        return TransportResult(sent == 1, "FOOD_FARM_CONSEQUENTIAL_INPUT_SENT" if sent == 1 else
                               "FOOD_FARM_INPUT_NOT_DISPATCHED")

    def recapture():
        return observation

    def post_observe():
        for captured in post_captures:
            semantic = post_values.get(str(captured.path), False)
            yield Observation(
                frame_sha256=str(captured.sha256),
                capture_completed_monotonic=float(captured.captured_monotonic),
                runtime_profile_id=runtime_profile_id,
                width=int(captured.frame.shape[1]), height=int(captured.frame.shape[0]),
                valid_png=True, corrupt=False, black=False,
                source_state=postcondition if semantic else "UNKNOWN",
                overlay_state="none_observed" if semantic else "unknown",
                target_identity=None, target_roi=None, recognized=bool(semantic),
                evidence_refs=(str(captured.path),),
            )

    execution = SafeActionExecutor(
        store, policy, session.owner,
        lambda: float(context.monotonic_clock()) if callable(getattr(context, "monotonic_clock", None)) else time.monotonic(),
        transport, recapture, post_observe,
        lambda _intent, observed: bool(
            post_captures and observed.frame_sha256 == post_captures[-1].sha256
            and post_values.get(str(post_captures[-1].path))
        ),
        wall_clock=lambda: float(context.utc_clock()) if callable(getattr(context, "utc_clock", None)) else time.time(),
        max_pre_dispatch_attempts=1,
    ).execute(request, issued.capability)
    row = store.get_action_by_key(action_key)
    transport_calls = int(execution.transport_calls)
    return {
        "status": "confirmed" if execution.status is ActionStatus.CONFIRMED else "unresolved" if execution.status is ActionStatus.UNRESOLVED else "blocked",
        "reason": execution.reason, "action_key": action_key,
        "journal_status": row.get("final_status") if row else None,
        "transport_calls": transport_calls,
        "effect_reconciliation_required": execution.status is ActionStatus.UNRESOLVED,
        "successor_frame": str(post_captures[-1].path) if post_captures else None,
        "successor_sha256": str(post_captures[-1].sha256) if post_captures else None,
    }


def _active_boost_from_capture(captured, *, farm_id: str, runtime_profile_id: str, session) -> BoostPanelRead | None:
    return observe_food_farm_boost_panel(
        captured, farm_identity=farm_id, runtime_profile_id=runtime_profile_id,
        evidence_ref=_evidence_ref(captured, session),
    )


def run_food_farm_boost_native(context, arguments: Mapping[str, object]) -> Mapping[str, object]:
    """Run one canonical Food Farm visit using the boundary's borrowed native owner."""
    if context.flow_id != FLOW_ID or context.product_id != PRODUCT_ID or context.product_revision != PRODUCT_REVISION:
        raise ValueError("Food Farm native context binding does not match this route")
    context.validate_identity()
    context.checkpoint()
    runtime, session, store = context.runtime, context.session, context.action_store
    identity = context.identity
    runtime_profile_id = str(getattr(identity, "runtime_profile_id", ACTIVE_RUNTIME_PROFILE_ID))
    if runtime_profile_id != ACTIVE_RUNTIME_PROFILE_ID:
        return {"status": "blocked", "reason": "FOOD_FARM_PROFILE_MISMATCH", "boost_transport_calls": 0,
                "collection_transport_calls": 0, "collection_count": 0, "collection_effect_accounted": False,
                "food_farm_dispatch_count": 0, "terminal_home_verified": False}
    occurrence_key = context.occurrence_key
    if type(occurrence_key) is not str or not occurrence_key or occurrence_key != occurrence_key.strip():
        raise ValueError("Food Farm requires the canonical service occurrence key")
    atlas_path = Path(str(arguments.get("atlas_path") or DEFAULT_ATLAS))
    atlas = load_home_atlas(atlas_path)
    localizer = BlueStacksHomeLocalizer(atlas, atlas_path)
    farm_capture = runtime.capture("food-farm-current-home-source")
    if not is_clean_home_frame(farm_capture.frame):
        return {"status": "blocked", "reason": "FOOD_FARM_HOME_NOT_CLEAN",
                "boost_transport_calls": 0, "collection_transport_calls": 0,
                "collection_count": 0, "collection_effect_accounted": False,
                "food_farm_dispatch_count": 0, "terminal_home_verified": False}
    home_localization = localizer.localize(farm_capture.frame)
    if not home_localization.recognized or home_localization.stale or home_localization.overlay:
        return {"status": "blocked", "reason": "FOOD_FARM_HOME_ATLAS_UNRECOGNIZED",
                "boost_transport_calls": 0, "collection_transport_calls": 0,
                "collection_count": 0, "collection_effect_accounted": False,
                "food_farm_dispatch_count": 0, "terminal_home_verified": False}
    binding = bind_reachable_farm(
        farm_capture.frame, atlas, localizer, localization=home_localization
    )
    if binding is None:
        return {"status": "deferred", "reason": "NO_FRESH_REACHABLE_MAPPED_FARM", "boost_transport_calls": 0,
                "collection_transport_calls": 0, "collection_count": 0, "collection_effect_accounted": False,
                "food_farm_dispatch_count": 0, "terminal_home_verified": True,
                "terminal_home_frame_sha256": farm_capture.sha256,
                "effect_reconciliation_required": False, "identical_retry_denied": False}

    base = {
        "farm_identity": binding.building_id,
        "reset_id": identity.reset_id,
        "boost_transport_calls": 0,
        "collection_transport_calls": 0,
        "collection_count": 0,
        "collection_effect_accounted": False,
        "collection_occurrence_key": occurrence_key,
        "boost_occurrence_key": None,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "terminal_home_verified": False,
        "food_farm_dispatch_count": 0,
    }
    collection_key = food_farm_boost_daily_action_key(
        runtime_scope=_identity_value(identity, "runtime_scope"),
        account_id=_identity_value(identity, "account_id"),
        server_id=_identity_value(identity, "server_id"),
        reset_id=_identity_value(identity, "reset_id"), phase="collection",
        # The route-owned quota is reset + ordinal, not the caller's opaque occurrence.
        collection_occurrence_id="1",
    )
    boost_key = food_farm_boost_daily_action_key(
        runtime_scope=_identity_value(identity, "runtime_scope"),
        account_id=_identity_value(identity, "account_id"),
        server_id=_identity_value(identity, "server_id"),
        reset_id=_identity_value(identity, "reset_id"), phase="boost",
    )
    base["collection_action_key"] = collection_key
    base["boost_occurrence_key"] = boost_key
    collection_row = store.get_action_by_key(collection_key)
    collection_state = food_farm_canonical_action_state(collection_row)
    # The reset-scoped confirmed row is a commit, but not a new transport attempt.
    if collection_state == "complete":
        base.update(collection_count=1, collection_effect_accounted=True)
    if collection_state == "reconciliation_required" or collection_state == "unknown":
        return {**base, "status": "blocked", "reason": "FOOD_FARM_COLLECTION_REQUIRES_RECONCILIATION",
                "effect_reconciliation_required": True, "identical_retry_denied": True}
    boost_row = store.get_action_by_key(boost_key)
    boost_state = food_farm_canonical_action_state(boost_row)
    if boost_state == "reconciliation_required" or boost_state == "unknown":
        return {**base, "status": "blocked", "reason": "FOOD_FARM_BOOST_REQUIRES_RECONCILIATION",
                "effect_reconciliation_required": True, "identical_retry_denied": True}
    if boost_state == "complete":
        if not _prior_boost_confirmation_matches(boost_row, binding.building_id):
            return {**base, "status": "blocked",
                    "reason": "FOOD_FARM_PRIOR_BOOST_CONFIRMATION_NOT_BOUND_TO_CURRENT_FARM",
                    "effect_reconciliation_required": True, "identical_retry_denied": True}
        return {**base, "status": "already_complete", "reason": "FOOD_FARM_BOOST_CONFIRMED_FOR_RESET",
                "terminal_home_verified": True, "terminal_home_frame_sha256": farm_capture.sha256,
                "boost_decision": "owned_item", "boost_duration_seconds": ONE_DAY_SECONDS,
                "prior_boost_confirmation_farm_identity": binding.building_id,
                "prior_boost_confirmation_duration_seconds": ONE_DAY_SECONDS,
                "prior_boost_confirmation": _json_mapping(boost_row.get("reconciliation_result_json"))}
    active_observations = [
        event for event in store.audit_events(boost_key)
        if event.get("task_id") == FLOW_ID and event.get("event_type") == "food_farm_active_boost_observed"
    ]
    if active_observations:
        prior_active = _json_mapping(active_observations[-1].get("payload_json"))
        if (
            prior_active.get("reset_id") != identity.reset_id
            or prior_active.get("farm_identity") != binding.building_id
            or type(prior_active.get("remaining_seconds")) is not int
            or prior_active.get("remaining_seconds") <= 0
            or not isinstance(prior_active.get("source_frame_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", prior_active["source_frame_sha256"]) is None
        ):
            return {**base, "status": "blocked",
                    "reason": "FOOD_FARM_PRIOR_ACTIVE_TIMER_NOT_BOUND_TO_CURRENT_FARM",
                    "effect_reconciliation_required": True, "identical_retry_denied": True}
        return {**base, "status": "already_complete",
                "reason": "FOOD_FARM_POSITIVE_BOOST_TIMER_PREVIOUSLY_OBSERVED",
                "terminal_home_verified": True, "terminal_home_frame_sha256": farm_capture.sha256,
                "active_remaining_seconds": prior_active["remaining_seconds"],
                "active_timer_farm_identity": binding.building_id,
                "prior_active_boost_observation": prior_active}

    if collection_state == "ready":
        balances_before = observe_home_resource_balances(farm_capture.frame)
        if any(type(balances_before.get(key)) is not int for key in FOOD_FARM_RESOURCE_TYPES):
            return {**base, "status": "deferred", "reason": "FOOD_FARM_COLLECTION_BALANCES_NOT_EXACT",
                    "terminal_home_verified": True, "terminal_home_frame_sha256": farm_capture.sha256,
                    "collection_balances_before": balances_before}
        preconditions = (
            f"product_id:{PRODUCT_ID}", f"product_revision:{PRODUCT_REVISION}",
            f"reset_identity:{identity.reset_id}", "effect_ordinal:collection=1",
            f"current_clean_home_atlas_binding:{binding.building_id}",
            "current_collection_balance_before:food={FOOD},wood={WOOD},steel={STEEL},gas={GAS}".format(
                FOOD=balances_before["FOOD"], WOOD=balances_before["WOOD"],
                STEEL=balances_before["STEEL"], GAS=balances_before["GAS"]),
            f"canonical_collection_action_key_unclaimed:{collection_key}", "current_runtime_lease_valid",
        )
        # The action is explicitly consequential; a tap that only opens a menu is not
        # promoted to success unless exact broad resource deltas are observed.
        if store.has_action_block():
            return {**base, "status": "blocked", "reason": "CANONICAL_ACTION_REQUIRES_RECONCILIATION",
                    "effect_reconciliation_required": True, "identical_retry_denied": True}
        capture_after = {}
        def collection_after(captured):
            if not is_clean_home_frame(captured.frame):
                return False
            rebound = bind_reachable_farm(captured.frame, atlas, localizer)
            if rebound is None or rebound.building_id != binding.building_id:
                return False
            balances_after = observe_home_resource_balances(captured.frame)
            verified, delta, why = food_farm_collection_effect(
                balances_before, balances_after, home_successor_verified=True
            )
            capture_after.update(balances=balances_after, delta=delta, reason=why, verified=verified,
                                 rebound=rebound)
            return verified
        action = _dispatch_canonical_action(
            context=context, binding=binding, source_capture=farm_capture,
            target_roi=binding.target_roi, action_key=collection_key,
            action_kind="collect_food_farm_resources", source_state="HOME_BASE",
            control_class="COLLECT", consequence="collect_all_base_resource_building_output",
            postcondition="FOOD_FARM_COLLECTION_RECONCILED",
            action_class=ActionClass.ZERO_COST_CONSEQUENTIAL, cost_type="none", cost_amount=0,
            maximum_cost=0, subject=binding.building_id,
            semantic_preconditions=preconditions,
            after_observer=collection_after,
            runtime_profile_id=runtime_profile_id,
        )
        collection_accounted = bool(
            action["status"] == "confirmed" and capture_after.get("verified")
        )
        base.update(collection_transport_calls=action["transport_calls"],
                    collection_count=int(collection_accounted), collection_action=action,
                    collection_balances_before=balances_before,
                    collection_balances_after=capture_after.get("balances"),
                    collection_deltas=capture_after.get("delta"),
                    collection_effect_accounted=collection_accounted)
        base["food_farm_dispatch_count"] = action["transport_calls"]
        if action["status"] != "confirmed":
            return {**base, "status": action["status"], "reason": action["reason"],
                    "effect_reconciliation_required": bool(action["effect_reconciliation_required"] or action["transport_calls"]),
                    "identical_retry_denied": bool(action["transport_calls"])}
        farm_capture = runtime.capture("food-farm-after-collection-home")
        binding = bind_reachable_farm(farm_capture.frame, atlas, localizer)
        rebound_after = capture_after.get("rebound")
        if binding is None or rebound_after is None or binding.building_id != rebound_after.building_id:
            return {**base, "status": "blocked", "reason": "FOOD_FARM_REBIND_AFTER_COLLECTION_FAILED",
                    "effect_reconciliation_required": True, "identical_retry_denied": True}

    # A same-reset confirmed boost is never issued again, even if its timer later expires.
    if store.action_key_exists(boost_key):
        row = store.get_action_by_key(boost_key)
        state = food_farm_canonical_action_state(row)
        if state != "ready":
            return {**base, "status": "blocked", "reason": "FOOD_FARM_BOOST_KEY_ALREADY_USED",
                    "effect_reconciliation_required": state != "complete", "identical_retry_denied": True}

    # Tap the same, freshly rebound Farm only after the collection occurrence is
    # accounted. The next surface must be the recognized Details/Upgrade/Boost radial.
    radial_source = runtime.capture("food-farm-rebound-before-radial")
    if not is_clean_home_frame(radial_source.frame):
        return {**base, "status": "blocked", "reason": "FOOD_FARM_HOME_LOST_BEFORE_RADIAL"}
    fresh_binding = bind_reachable_farm(radial_source.frame, atlas, localizer)
    if fresh_binding is None or fresh_binding.building_id != binding.building_id:
        return {**base, "status": "blocked", "reason": "FOOD_FARM_REBIND_BEFORE_RADIAL_FAILED"}
    # The native radial recognizer is deliberately exact; the visible tap is a
    # navigation successor only after the earlier collection is durably confirmed.
    radial_result = _open_food_farm_radial(context, atlas, localizer, fresh_binding)
    if radial_result.get("status") != "opened":
        return {**base, **radial_result, "status": radial_result.get("status", "blocked")}
    panel_result = _open_food_farm_boost_panel(context, farm_id=binding.building_id, binding=fresh_binding)
    if panel_result.get("status") != "observed":
        return {**base, **panel_result, "status": panel_result.get("status", "blocked")}
    panel = panel_result["panel"]
    decision = food_farm_boost_decision(panel.observation)

    def terminal_home():
        current = runtime.capture("food-farm-before-terminal-home-check")
        if is_clean_home_frame(current.frame):
            localized = localizer.localize(current.frame)
            if localized.recognized and not localized.stale and not localized.overlay:
                return {"status": "home", "terminal_home_verified": True,
                        "terminal_home_frame_sha256": current.sha256,
                        "terminal_home_frame": str(current.path)}
        if observe_food_farm_boost_panel(
            current, farm_identity=binding.building_id, runtime_profile_id=runtime_profile_id,
            evidence_ref=_evidence_ref(current, session),
        ) is not None:
            return _return_home_from_boost_panel(
                context, farm_id=binding.building_id, localizer=localizer
            )
        return {"status": "blocked", "reason": "FOOD_FARM_TERMINAL_SURFACE_UNKNOWN"}

    if decision.choice is FoodFarmBoostChoice.ALREADY_ACTIVE:
        active_seconds = panel.observation.active_remaining_seconds
        if type(active_seconds) is not int or not 0 < active_seconds <= ONE_DAY_SECONDS:
            home = terminal_home()
            return {**base, **home, "status": "blocked",
                    "reason": "FOOD_FARM_ACTIVE_TIMER_NOT_EXACT_ONE_DAY_RANGE",
                    "boost_decision": decision.choice.value, "evidence_required": True}
        observed_at = float(context.utc_clock()) if callable(getattr(context, "utc_clock", None)) else time.time()
        store.audit(
            FLOW_ID, "food_farm_active_boost_observed", observed_at,
            {"reset_id": identity.reset_id, "farm_identity": binding.building_id,
             "remaining_seconds": panel.observation.active_remaining_seconds,
             "source_frame_sha256": panel.observation.source_frame_sha256},
            action_id=boost_key,
        )
        home = terminal_home()
        if home["status"] != "home":
            return {**base, **home, "status": "blocked", "boost_decision": decision.choice.value}
        return {**base, **home, "status": "already_active", "reason": decision.reason,
                "boost_decision": decision.choice.value,
                "active_remaining_seconds": panel.observation.active_remaining_seconds,
                "active_timer_farm_identity": binding.building_id}
    if decision.choice is FoodFarmBoostChoice.BLOCKED:
        home = terminal_home()
        return {**base, **home, "status": "blocked",
                "reason": decision.reason if home["status"] == "home" else home.get("reason"),
                "boost_decision": decision.choice.value, "boost_panel_text": panel.text,
                "evidence_required": True, "effect_reconciliation_required": False,
                "identical_retry_denied": False}
    if decision.choice is FoodFarmBoostChoice.DIAMONDS:
        home = terminal_home()
        return {**base, **home, "status": "blocked",
                "reason": "FOOD_FARM_DIAMOND_CONFIRMATION_EVIDENCE_REQUIRED",
                "boost_decision": decision.choice.value, "evidence_required": True}
    if decision.choice is not FoodFarmBoostChoice.OWNED_ITEM:
        home = terminal_home()
        return {**base, **home, "status": "blocked",
                "reason": "FOOD_FARM_BOOST_DECISION_UNKNOWN", "evidence_required": True}
    if decision.duration_seconds != ONE_DAY_SECONDS:
        home = terminal_home()
        return {**base, **home, "status": "blocked",
                "reason": "FOOD_FARM_EXACT_ONE_DAY_DURATION_REQUIRED",
                "boost_decision": decision.choice.value, "evidence_required": True}

    button_roi = panel.item_control_roi
    if button_roi is None:
        home = terminal_home()
        return {**base, **home, "status": "blocked",
                "reason": "FOOD_FARM_EXACT_ACTION_CONTROL_UNBOUND",
                "boost_decision": decision.choice.value, "evidence_required": True}
    boost_preconditions = (
        f"product_id:{PRODUCT_ID}", f"product_revision:{PRODUCT_REVISION}",
        f"reset_identity:{identity.reset_id}", "effect_ordinal:boost=1",
        f"current_food_farm_boost_panel_binding:{binding.building_id}",
        f"exact_current_food_farm_item_name:{decision.item_name}",
        f"exact_current_food_farm_item_duration_seconds:{decision.duration_seconds}",
        f"canonical_food_farm_boost_action_key_unclaimed:{boost_key}",
        "current_runtime_lease_valid",
        "current_exact_owned_food_farm_item_count_at_least_one",
        "current_food_farm_item_action_cost:1",
    )
    consequence = "consume_one_exact_named_owned_food_farm_output_boost_item"
    cost_type = "owned_item"
    panel_binding = FarmBinding(
        binding.building_id, tuple(int(value) for value in button_roi),
        panel.source_capture.sha256, binding.evidence + ("recognized_food_farm_boost_panel",),
    )

    boost_postcondition = {}

    def boost_after(captured):
        observed = _active_boost_from_capture(
            captured, farm_id=binding.building_id,
            runtime_profile_id=runtime_profile_id, session=session,
        )
        remaining = observed.observation.active_remaining_seconds if observed else None
        verified = bool(
            decision.duration_seconds == ONE_DAY_SECONDS
            and type(remaining) is int and 0 < remaining <= ONE_DAY_SECONDS
            and observed and food_farm_boost_postcondition_verified(panel.observation, observed.observation)
        )
        if verified:
            boost_postcondition.update(
                remaining_seconds=observed.observation.active_remaining_seconds,
                farm_identity=observed.observation.farm_identity,
            )
        return verified
    action = _dispatch_canonical_action(
        context=context, binding=panel_binding, source_capture=panel.source_capture,
        target_roi=panel_binding.target_roi, action_key=boost_key,
        action_kind="apply_food_farm_output_boost_owned_item",
        source_state="FOOD_FARM_BOOST_PANEL", control_class="BOOST",
        consequence=consequence, postcondition="FOOD_FARM_POSITIVE_BOOSTING_TIMER",
        action_class=ActionClass.SPEND_OR_STRATEGIC, cost_type=cost_type,
        cost_amount=float(decision.cost or 1), maximum_cost=float(decision.cost or 1),
        subject=_item_subject(str(decision.item_name or "")), semantic_preconditions=boost_preconditions,
        after_observer=boost_after, runtime_profile_id=runtime_profile_id,
    )
    base["boost_transport_calls"] = action["transport_calls"]
    base["food_farm_dispatch_count"] = int(base["collection_transport_calls"]) + action["transport_calls"]
    base["boost_duration_seconds"] = decision.duration_seconds
    if boost_postcondition:
        base["boost_timer_remaining_seconds"] = boost_postcondition["remaining_seconds"]
        base["boost_timer_farm_identity"] = boost_postcondition["farm_identity"]
    base["boost_action"] = action
    if action["status"] != "confirmed":
        base["effect_reconciliation_required"] = bool(
            action["effect_reconciliation_required"] or action["transport_calls"]
        )
        base["identical_retry_denied"] = bool(action["transport_calls"])
        home = terminal_home()
        if home["status"] == "home":
            base.update(home)
        return {**base, "status": "unresolved" if action["transport_calls"] else "blocked",
                "reason": action["reason"], "boost_decision": decision.choice.value}
    home = terminal_home()
    if home["status"] != "home":
        return {**base, **home, "status": "blocked", "reason": "FOOD_FARM_BOOST_TERMINAL_HOME_UNVERIFIED",
                "effect_reconciliation_required": True, "identical_retry_denied": True}
    return {**base, **home, "status": "completed", "reason": "FOOD_FARM_BOOST_CONFIRMED_WITH_POSITIVE_TIMER",
            "boost_decision": decision.choice.value}


def _farm_radial_boost_roi(frame: np.ndarray, binding: FarmBinding) -> tuple[int, int, int, int] | None:
    tokens = _ocr_tokens(frame)
    fx0, fy0, fx1, fy1 = binding.target_roi
    anchor = ((fx0 + fx1) / 2, (fy0 + fy1) / 2)
    labels = {}
    for label in ("details", "upgrade", "boost"):
        found = [
            token for token in tokens
            if token.text.casefold().strip(" :") == label
            and abs((token.roi[0] + token.roi[2]) / 2 - anchor[0]) <= 280
            and abs((token.roi[1] + token.roi[3]) / 2 - anchor[1]) <= 220
        ]
        if len(found) != 1:
            return None
        labels[label] = found[0]
    farm_labels = [
        token for token in tokens
        if token.text.casefold().strip(" :") == "farm"
        and abs((token.roi[0] + token.roi[2]) / 2 - anchor[0]) <= 70
        and abs((token.roi[1] + token.roi[3]) / 2 - anchor[1]) <= 45
    ]
    if len(farm_labels) != 1:
        return None
    boost = labels["boost"]
    roi = (boost.roi[0] - 8, boost.roi[1] - 8, boost.roi[2] + 8, boost.roi[3] + 8)
    sx0, sy0, sx1, sy1 = BLUESTACKS_SAFE_INTERACTION_BOX
    return roi if sx0 <= roi[0] < roi[2] <= sx1 and sy0 <= roi[1] < roi[3] <= sy1 else None


def _run_navigation_tap(
    context, *, label: str, target_identity: str, planned_roi: tuple[int, int, int, int],
    authorize, recognize,
) -> dict[str, Any]:
    runtime, session = context.runtime, context.session
    fresh: dict[str, tuple[int, int, int, int]] = {}

    starting_count = int(getattr(runtime, "input_count", 0))

    def admit(before):
        target_roi = authorize(before)
        if target_roi is None or tuple(target_roi) != tuple(planned_roi):
            raise RuntimeError("Food Farm navigation target no longer matches its current frame")
        fresh["target_roi"] = tuple(target_roi)

    def dispatch(before):
        context.checkpoint()
        context.validate_identity()
        runtime.tap(
            before, target_identity=target_identity, target_roi=fresh["target_roi"],
            action_key=label, action_class="navigation", consequential=False,
        )

    def settled():
        time.sleep(float(getattr(context, "settle_seconds", 1.0)))
        context.checkpoint()
        context.validate_identity()
        return runtime.capture(f"{label}-settled")

    result = session.run_action(
        action_class="navigation", label=label, capture=runtime.capture,
        dispatch=dispatch, recognize=lambda after: "recognized" if recognize(after) else "unknown",
        authorize=admit, consequence_class="navigation_only", settled_successor=settled,
    )
    input_count = int(getattr(runtime, "input_count", 0)) - starting_count
    opened = result.status == "completed" and input_count == 1
    return {
        "status": "opened" if opened else "blocked",
        "reason": result.reason if opened else "FOOD_FARM_NAVIGATION_INPUT_NOT_CONFIRMED",
        "state": result.state,
        "input_count": input_count, "source_sha256": result.before_sha256,
        "successor_sha256": result.after_sha256,
    }


def _open_food_farm_radial(context, atlas, localizer, binding: FarmBinding) -> dict[str, Any]:
    """Open the same currently bound Farm after its collection effect was reconciled."""
    def authorize(before):
        if not is_clean_home_frame(before.frame):
            return None
        rebound = bind_reachable_farm(before.frame, atlas, localizer)
        return rebound.target_roi if rebound and rebound.building_id == binding.building_id else None

    def recognize(after):
        return _farm_radial_boost_roi(after.frame, binding) is not None

    result = _run_navigation_tap(
        context, label=f"food-farm-open-radial-{context.session.invocation_id}",
        target_identity=binding.building_id, planned_roi=binding.target_roi,
        authorize=authorize, recognize=recognize,
    )
    if result["status"] != "opened":
        return result
    opened = context.runtime.capture("food-farm-radial-current")
    control = _farm_radial_boost_roi(opened.frame, binding)
    return {**result, "status": "opened" if control is not None else "blocked",
            "reason": "recognized_same_farm_radial" if control is not None else "radial_successor_lost",
            "radial_capture": opened, "boost_control_roi": control}


def _open_food_farm_boost_panel(context, *, farm_id: str, binding: FarmBinding) -> dict[str, Any]:
    runtime = context.runtime
    radial_capture = runtime.capture("food-farm-radial-before-boost")
    boost_roi = _farm_radial_boost_roi(radial_capture.frame, binding)
    if boost_roi is None:
        return {"status": "blocked", "reason": "FOOD_FARM_BOOST_CONTROL_NOT_BOUND"}

    def authorize(before):
        return _farm_radial_boost_roi(before.frame, binding)

    def recognize(after):
        return observe_food_farm_boost_panel(
            after, farm_identity=farm_id, runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            evidence_ref=_evidence_ref(after, context.session),
        ) is not None

    result = _run_navigation_tap(
        context, label=f"food-farm-open-boost-panel-{context.session.invocation_id}",
        target_identity=f"food-farm-radial-boost:{farm_id}", planned_roi=boost_roi,
        authorize=authorize, recognize=recognize,
    )
    if result["status"] != "opened":
        return result
    panel_capture = runtime.capture("food-farm-boost-panel-current")
    panel = observe_food_farm_boost_panel(
        panel_capture, farm_identity=farm_id, runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        evidence_ref=_evidence_ref(panel_capture, context.session),
    )
    return {**result, "status": "observed" if panel is not None else "blocked",
            "reason": "food_farm_boost_panel_recognized" if panel is not None else "boost_panel_unknown",
            "panel": panel}


def _return_home_from_boost_panel(context, *, farm_id: str, localizer) -> dict[str, Any]:
    runtime, session = context.runtime, context.session

    def authorize(before):
        if observe_food_farm_boost_panel(
            before, farm_identity=farm_id, runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
            evidence_ref=_evidence_ref(before, session),
        ) is None:
            raise RuntimeError("Food Farm Boost panel is not positively recognized before Escape")

    def dispatch(before):
        context.checkpoint()
        context.validate_identity()
        runtime.press_key(
            before, key="Escape",
            action_key=f"food-farm-return-home-{session.invocation_id}",
        )

    def recognize(after):
        if not is_clean_home_frame(after.frame):
            return "unknown"
        localization = localizer.localize(after.frame)
        return "verified_home" if localization.recognized and not localization.stale and not localization.overlay else "unknown"

    def settled():
        time.sleep(float(getattr(context, "settle_seconds", 1.0)))
        context.checkpoint()
        context.validate_identity()
        return runtime.capture("food-farm-return-home-settled")

    try:
        result = session.run_action(
            action_class="navigation", label=f"food-farm-return-home-{session.invocation_id}",
            capture=runtime.capture, dispatch=dispatch, recognize=recognize,
            authorize=authorize, consequence_class="navigation_only", settled_successor=settled,
        )
    except Exception as exc:
        return {"status": "blocked", "reason": f"FOOD_FARM_RETURN_HOME_FAILED:{type(exc).__name__}"}
    if result.status != "completed":
        return {"status": "blocked", "reason": "FOOD_FARM_HOME_SUCCESSOR_UNKNOWN"}
    final = runtime.capture("food-farm-terminal-home")
    if recognize(final) != "verified_home":
        return {"status": "blocked", "reason": "FOOD_FARM_TERMINAL_HOME_NOT_PROVEN"}
    return {"status": "home", "terminal_home_verified": True,
            "terminal_home_frame_sha256": final.sha256, "terminal_home_frame": str(final.path)}


def create_service_binding(make_native_route_binding):
    """Bind this route to the canonical native owner without opening a device at import."""
    return make_native_route_binding(
        flow_id=FLOW_ID,
        product_id=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        runtime_profile_id=ACTIVE_RUNTIME_PROFILE_ID,
        owner="automation-service:food-farm-boost",
        workflow="food-farm-output-boost",
        max_inputs=MAX_INPUTS,
        max_actions=MAX_ACTIONS,
        driver=run_food_farm_boost_native,
        validator=validate_food_farm_native_result,
        lease_seconds=3600.0,
    )


def validate_food_farm_native_result(result: Mapping[str, object]) -> bool:
    """Validate attempts separately from committed collection effects."""
    collection_calls = result.get("collection_transport_calls")
    boost_calls = result.get("boost_transport_calls")
    dispatch_count = result.get("food_farm_dispatch_count")
    collection_count = result.get("collection_count")
    if any(type(value) is not int or value < 0 for value in (collection_calls, boost_calls, dispatch_count, collection_count)):
        return False
    if (
        collection_calls > 1 or boost_calls > 1
        or dispatch_count != collection_calls + boost_calls
        or collection_count > 1
    ):
        return False
    if collection_count and result.get("collection_effect_accounted") is not True:
        return False
    if (
        collection_calls > 0
        and result.get("collection_effect_accounted") is True
        and collection_count != 1
    ):
        return False
    if (
        collection_calls > 0
        and result.get("collection_effect_accounted") is not True
        and result.get("effect_reconciliation_required") is not True
    ):
        return False
    status = result.get("status")
    if status in {"completed", "already_active", "already_complete", "deferred"}:
        if result.get("effect_reconciliation_required") is not False:
            return False
        if (
            result.get("terminal_home_verified") is not True
            or not isinstance(result.get("terminal_home_frame_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", result["terminal_home_frame_sha256"]) is None
        ):
            return False
    farm_id = result.get("farm_identity")
    if status == "completed":
        timer = result.get("boost_timer_remaining_seconds")
        if (
            boost_calls != 1
            or result.get("boost_decision") != FoodFarmBoostChoice.OWNED_ITEM.value
            or result.get("boost_duration_seconds") != ONE_DAY_SECONDS
            or type(timer) is not int or not 0 < timer <= ONE_DAY_SECONDS
            or type(farm_id) is not str or _FARM_ID.fullmatch(farm_id) is None
            or result.get("boost_timer_farm_identity") != farm_id
        ):
            return False
    elif status == "already_active":
        timer = result.get("active_remaining_seconds")
        if (
            boost_calls != 0
            or type(timer) is not int or not 0 < timer <= ONE_DAY_SECONDS
            or type(farm_id) is not str or _FARM_ID.fullmatch(farm_id) is None
            or result.get("active_timer_farm_identity") != farm_id
        ):
            return False
    elif status == "already_complete":
        if boost_calls != 0 or type(farm_id) is not str or _FARM_ID.fullmatch(farm_id) is None:
            return False
        confirmation = result.get("prior_boost_confirmation")
        prior_active = result.get("prior_active_boost_observation")
        confirmed_action = bool(
            isinstance(confirmation, Mapping)
            and confirmation.get("confirmed") is True
            and isinstance(confirmation.get("frame_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", confirmation["frame_sha256"]) is not None
            and result.get("prior_boost_confirmation_farm_identity") == farm_id
            and result.get("prior_boost_confirmation_duration_seconds") == ONE_DAY_SECONDS
        )
        active_timer = (
            prior_active.get("remaining_seconds")
            if isinstance(prior_active, Mapping) else None
        )
        confirmed_active = bool(
            isinstance(prior_active, Mapping)
            and prior_active.get("reset_id") == result.get("reset_id")
            and prior_active.get("farm_identity") == farm_id
            and type(active_timer) is int and 0 < active_timer <= ONE_DAY_SECONDS
            and isinstance(prior_active.get("source_frame_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", prior_active["source_frame_sha256"]) is not None
        )
        if not (confirmed_action or confirmed_active):
            return False
    elif status == "deferred":
        if collection_calls or boost_calls:
            return False
    if boost_calls and not result.get("effect_reconciliation_required") and status not in {"completed", "already_active"}:
        return False
    return True
