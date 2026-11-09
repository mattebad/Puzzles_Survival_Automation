from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
from types import SimpleNamespace

import cv2
import numpy as np

import pytest

from automation_service.recruitment import recruitment_reset
from automation_service.troop_training import (
    FLOW_ID,
    PRODUCT_ID,
    TroopTrainingRunner,
    TrainingActionHistoryError,
    derive_training_action_state,
    make_training_claim_action_key,
    make_training_start_action_key,
    training_identity_digest,
)
from tasks.runtime_identity import resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity
from automation_service.state import BotStateManager
from safe_action_core import SafetyStore
from scripts import base_route_native_runtime as native_runtime
from scripts import troop_training_bluestacks as training_native
from scripts.bluestacks_native_runtime import CapturedNativeFrame
from tasks.troop_training import TROOP_TYPES, ResourceReading
from tests.support.service_route_contract import ROUTES, RouteRig
from tests.test_troop_training import observation




def _identity(now: float) -> SchedulerIdentity:
    binding = resource_fixed_runtime_binding()
    return SchedulerIdentity(
        binding.account_id,
        binding.server_id,
        recruitment_reset(now),
        PRODUCT_ID,
    )


def _row(
    action_key: str, *, reset_id: str, status: str, semantic_action: str, quantity: int = 250,
) -> dict[str, object]:
    return {
        "task_id": FLOW_ID,
        "action_key": action_key,
        "final_status": status,
        "game_day_id": reset_id,
        "semantic_action": semantic_action,
        "quantity": quantity,
    }



def test_action_state_keeps_global_generation_daily_counts_and_old_batch_identity():
    binding = resource_fixed_runtime_binding()
    runtime_hash = training_identity_digest(
        binding.runtime_scope,
        binding.account_id,
        binding.server_id,
    )
    current_reset = "game-day-2025-01-02"
    prior_reset = "game-day-2025-01-01"
    prior_fighter = make_training_start_action_key(runtime_hash, prior_reset, "fighter", 1)
    prior_fighter_claim = make_training_claim_action_key(prior_fighter)
    shooter_today = make_training_start_action_key(runtime_hash, current_reset, "shooter", 1)
    unresolved_vehicle = make_training_start_action_key(runtime_hash, current_reset, "vehicle", 1)
    rows = [
        _row(prior_fighter, reset_id=prior_reset, status="confirmed", semantic_action="TROOP_TRAINING_START"),
        _row(prior_fighter_claim, reset_id=current_reset, status="confirmed", semantic_action="TROOP_TRAINING_COMPLETED_BATCH_CLAIM"),
        _row(shooter_today, reset_id=current_reset, status="confirmed", semantic_action="TROOP_TRAINING_START"),
        _row(unresolved_vehicle, reset_id=current_reset, status="unresolved", semantic_action="TROOP_TRAINING_START"),
        {"task_id": PRODUCT_ID, "action_key": "not-a-native-row"},
    ]

    state = derive_training_action_state(
        rows,
        runtime_scope=binding.runtime_scope,
        account_id=binding.account_id,
        server_id=binding.server_id,
        game_day_id=current_reset,
    )
    assert state.runtime_identity_sha256 == runtime_hash
    assert state.queue_generations["fighter"] == 1
    assert state.queue_generations["shooter"] == 1
    assert state.prior_daily_initiations == frozenset({"shooter"})
    assert state.per_reset_variant_start_counts["shooter"] == 1
    assert state.per_reset_variant_start_counts["fighter"] == 0
    assert state.per_reset_variant_claim_counts["fighter"] == 1
    assert state.pending_start_action_keys == {"shooter": shooter_today}
    assert state.prior_batch_quantities == {"shooter": 250}
    assert state.next_start_action_keys["fighter"].endswith(":fighter:g2:start")
    assert "vehicle" in state.blocked_start_variants
    assert "vehicle" not in state.next_start_action_keys


@pytest.mark.parametrize("troop", TROOP_TYPES)
@pytest.mark.parametrize("quantity", (None, 0, -1, True, "250"))
def test_pending_confirmed_start_requires_positive_stored_integer_quantity(troop, quantity):
    binding = resource_fixed_runtime_binding()
    runtime_hash = training_identity_digest(binding.runtime_scope, binding.account_id, binding.server_id)
    reset = "game-day-2025-01-02"
    row = _row(
        make_training_start_action_key(runtime_hash, reset, troop, 1),
        reset_id=reset, status="confirmed", semantic_action="TROOP_TRAINING_START",
    )
    if quantity is None:
        row.pop("quantity")
    else:
        row["quantity"] = quantity
    with pytest.raises(TrainingActionHistoryError, match="authorized batch quantity"):
        derive_training_action_state(
            [row], runtime_scope=binding.runtime_scope, account_id=binding.account_id,
            server_id=binding.server_id, game_day_id=reset,
        )


@pytest.mark.parametrize("troop", ("shooter", "rider"))
def test_pending_daily_batch_rejects_stored_quantity_other_than_250(troop):
    binding = resource_fixed_runtime_binding()
    runtime_hash = training_identity_digest(binding.runtime_scope, binding.account_id, binding.server_id)
    reset = "game-day-2025-01-02"
    with pytest.raises(TrainingActionHistoryError, match="quantity 250"):
        derive_training_action_state(
            [_row(
                make_training_start_action_key(runtime_hash, reset, troop, 1),
                reset_id=reset, status="confirmed", semantic_action="TROOP_TRAINING_START",
                quantity=1000,
            )],
            runtime_scope=binding.runtime_scope, account_id=binding.account_id,
            server_id=binding.server_id, game_day_id=reset,
        )


@pytest.mark.parametrize("troop", ("fighter", "vehicle"))
def test_pending_continuous_batch_retains_quantity_across_reset(troop):
    binding = resource_fixed_runtime_binding()
    runtime_hash = training_identity_digest(binding.runtime_scope, binding.account_id, binding.server_id)
    prior_reset = "game-day-2025-01-01"
    start = make_training_start_action_key(runtime_hash, prior_reset, troop, 1)
    state = derive_training_action_state(
        [_row(
            start, reset_id=prior_reset, status="confirmed",
            semantic_action="TROOP_TRAINING_START", quantity=731,
        )],
        runtime_scope=binding.runtime_scope, account_id=binding.account_id,
        server_id=binding.server_id, game_day_id="game-day-2025-01-02",
    )
    assert state.prior_batch_quantities == {troop: 731}
    assert state.pending_start_action_keys == {troop: start}
    assert state.pending_start_reset_ids == {troop: prior_reset}
    assert state.queue_generations[troop] == 1
    assert state.per_reset_variant_start_counts[troop] == 0
    assert troop not in state.next_start_action_keys


def test_unresolved_restart_and_duplicate_generations_are_manual_reconciliation():
    binding = resource_fixed_runtime_binding()
    runtime_hash = training_identity_digest(binding.runtime_scope, binding.account_id, binding.server_id)
    reset = "game-day-2025-01-02"
    unresolved = make_training_start_action_key(runtime_hash, reset, "rider", 1)
    state = derive_training_action_state(
        [_row(unresolved, reset_id=reset, status="input_sent", semantic_action="TROOP_TRAINING_START")],
        runtime_scope=binding.runtime_scope,
        account_id=binding.account_id,
        server_id=binding.server_id,
        game_day_id=reset,
    )
    assert state.queue_generations["rider"] == 0
    assert state.prior_daily_initiations == frozenset({"rider"})
    assert "rider" in state.blocked_start_variants
    assert "rider" not in state.next_start_action_keys

    duplicate_generation = make_training_start_action_key(runtime_hash, "game-day-2025-01-01", "fighter", 1)
    with pytest.raises(TrainingActionHistoryError, match="generation is duplicated"):
        derive_training_action_state(
            [
                _row(duplicate_generation, reset_id="game-day-2025-01-01", status="confirmed", semantic_action="TROOP_TRAINING_START"),
                _row(make_training_start_action_key(runtime_hash, reset, "fighter", 1), reset_id=reset, status="confirmed", semantic_action="TROOP_TRAINING_START"),
            ],
            runtime_scope=binding.runtime_scope,
            account_id=binding.account_id,
            server_id=binding.server_id,
            game_day_id=reset,
        )


@pytest.mark.parametrize(
    ("suffix", "status", "semantic_action"),
    (
        ("resource-box", "confirmed", "LEGACY_RESOURCE_BOX_EFFECT"),
        ("warehouse", "unresolved", "LEGACY_WAREHOUSE_EFFECT"),
    ),
)
def test_legacy_continuation_history_requires_manual_reconciliation_without_losing_progress(
    suffix,
    status,
    semantic_action,
):
    binding = resource_fixed_runtime_binding()
    runtime_hash = training_identity_digest(binding.runtime_scope, binding.account_id, binding.server_id)
    reset = "game-day-2025-01-02"
    start = make_training_start_action_key(runtime_hash, reset, "fighter", 1)
    claim = make_training_claim_action_key(start)
    rows = [
        _row(start, reset_id=reset, status="confirmed", semantic_action="TROOP_TRAINING_START"),
        _row(claim, reset_id=reset, status="confirmed", semantic_action="TROOP_TRAINING_COMPLETED_BATCH_CLAIM"),
        _row(
            f"{start}:{suffix}",
            reset_id=reset,
            status=status,
            semantic_action=semantic_action,
        ),
    ]
    original_rows = [dict(row) for row in rows]

    with pytest.raises(TrainingActionHistoryError, match="manual reconciliation"):
        derive_training_action_state(
            rows,
            runtime_scope=binding.runtime_scope,
            account_id=binding.account_id,
            server_id=binding.server_id,
            game_day_id=reset,
        )

    assert rows == original_rows
    progress = derive_training_action_state(
        rows[:2],
        runtime_scope=binding.runtime_scope,
        account_id=binding.account_id,
        server_id=binding.server_id,
        game_day_id=reset,
    )
    assert progress.queue_generations["fighter"] == 1
    assert progress.per_reset_variant_start_counts["fighter"] == 1
    assert progress.per_reset_variant_claim_counts["fighter"] == 1
    assert progress.prior_batch_quantities == {}





def test_missing_native_boundary_cannot_claim_completion_or_schedule(tmp_path):
    now = datetime(2025, 1, 2, 12, tzinfo=timezone.utc).timestamp()
    identity = _identity(now)
    result = TroopTrainingRunner(
        native=None,
        output_directory=Path(tmp_path),
        utc_clock=lambda: now,
    )(
        identity,
        None,
        lambda: None,
        runtime_input_lock=object(),
        occurrence_key="troop-training-missing-native",
    )
    assert result["status"] == "blocked"
    assert result["task_id"] == PRODUCT_ID
    assert result["native_task_id"] == FLOW_ID
    assert result["training_dispatch_count"] == 0
    assert result["terminal_home_verified"] is False
    assert result["accounting_verified"] is False


@pytest.fixture
def native_service():
    """Real service, Runner, native lifecycle, policy and journal; scripted UI only."""
    world = SimpleNamespace(
        modes={troop: "empty" for troop in TROOP_TYPES},
        current="fighter",
        uncertain_claim=False,
        after_claim_mode="empty",
        inputs=[],
        payloads=[],
        routes=[],
        monotonic=10.0,
        pre_dispatch_mode=None,
        preset_requests=[],
        maxima={troop: 1000 for troop in TROOP_TYPES},
        queue_quantities={},
    )

    class OfflineRuntime:
        def __init__(self, output_directory):
            self.session = output_directory / "offline-runtime"
            self.session.mkdir(parents=True)
            self.input_count = 0
            self.max_inputs = training_native.MAX_INPUTS
            self.in_flight_action = None
            self.ordinal = 0
            self.checkpoint = lambda: None

        def capture(self, label):
            world.monotonic += 0.1
            if label == "troop-training-start-pre-dispatch" and world.pre_dispatch_mode is not None:
                world.modes[world.current] = world.pre_dispatch_mode
            self.checkpoint()
            self.ordinal += 1
            mode = ("empty", "active", "completed", "shortage", "unknown").index(
                world.modes[world.current]
            )
            frame = np.full((1280, 800, 3), mode + 1, dtype=np.uint8)
            encoded, png = cv2.imencode(".png", frame)
            assert encoded
            payload = png.tobytes()
            path = self.session / f"{self.ordinal}-{label}.png"
            path.write_bytes(payload)
            return CapturedNativeFrame(
                frame, payload, hashlib.sha256(payload).hexdigest(), world.monotonic, path,
            )

        def measure_device_state(self):
            return "device"

        def measure_foreground_package(self):
            return "com.global.ztmslg"

        def tap(self, source, *, action_key, **kwargs):
            self.checkpoint()
            self.input_count += 1
            world.inputs.append(action_key)
            if action_key.endswith(":claim"):
                world.modes[world.current] = (
                    "unknown" if world.uncertain_claim else world.after_claim_mode
                )
            else:
                world.queue_quantities[world.current] = (
                    world.maxima[world.current] if world.current in {"fighter", "vehicle"} else 250
                )
                world.modes[world.current] = "active"

    def recognize(frame):
        troop = world.current
        mode = ("empty", "active", "completed", "shortage", "unknown")[int(frame[0, 0, 0]) - 1]
        quantity = world.maxima[troop] if troop in {"fighter", "vehicle"} else 250
        tier = 8 if troop in {"fighter", "shooter"} else 1
        queued = mode in {"active", "completed"}
        queue_quantity = world.queue_quantities.get(troop) if queued else None
        seen = replace(
            observation(troop, tier=tier, quantity=quantity),
            recognized=mode != "unknown",
            quantity_maximum=world.maxima[troop],
            captured_at=datetime.fromtimestamp(world.rig.stop.now, timezone.utc),
            frame_sha256=hashlib.sha256(cv2.imencode(".png", frame)[1].tobytes()).hexdigest(),
            queue_active=mode == "active",
            completion_ready=mode == "completed",
            queue_label=f"Train T{tier} {troop} x{queue_quantity}" if queued else None,
            queue_troop_type=troop if queued else None,
            queue_tier=tier if queued else None,
            queue_quantity=queue_quantity,
            diagnostics={
                "duration_source": "queue_band" if queued else "normal_train_band",
                "queue_spatially_associated": queued,
            },
        )
        if mode == "shortage":
            seen = replace(
                seen,
                resources=tuple(
                    ResourceReading(name, 0, 1000, "base")
                    for name in ("food", "wood", "steel", "gas")
                ),
            )
        return SimpleNamespace(
            observation=seen,
            target=lambda name: (
                seen.normal_train_target if name == "train" else (30, 100, 150, 180)
            ),
        )

    def enter_training(route):
        world.routes.append(route)
        world.current = "fighter"
        source = route.runtime.capture("training-entry")
        return route._run_training_tabs(
            source, recognize(source.frame).observation, list(TROOP_TYPES), "fighter",
        )

    def switch_tab(route, _source, _seen, troop):
        world.current = troop
        source = route.runtime.capture(f"visible-tab-{troop}")
        return source, recognize(source.frame).observation, None

    def saved_preset_observation(session, runtime, preset_name, **kwargs):
        assert preset_name == "Training"
        assert kwargs["switch_approval"] is None
        assert kwargs["context"]["required_preset"] == "Training"
        assert kwargs["runtime_input_lock"].held
        world.preset_requests.append(preset_name)
        return SimpleNamespace(verified=True, preset_name=preset_name)

    def driver(context, arguments):
        payload = training_native.run_troop_training_native(context, arguments)
        world.payloads.append(payload)
        return payload

    def make_runner(stop, root):
        world.store_path = root / "native-actions.sqlite3"
        boundary = native_runtime.make_native_route_binding(
            flow_id=FLOW_ID,
            product_id=PRODUCT_ID,
            product_revision=training_native.PRODUCT_REVISION,
            runtime_profile_id=training_native.PROFILE_ID,
            owner="automation-service:troop-training",
            workflow="troop-training-native",
            max_inputs=training_native.MAX_INPUTS,
            max_actions=training_native.MAX_ACTIONS,
            driver=driver,
            action_store_factory=lambda _path: SafetyStore(world.store_path),
        )
        return TroopTrainingRunner(
            native=boundary, output_directory=root / "native-sessions",
            monotonic_clock=lambda: world.monotonic,
            utc_clock=lambda: stop.now, settle_seconds=0,
        )

    with ExitStack() as stack:
        spec = replace(ROUTES[FLOW_ID], make_runner=make_runner)
        rig = RouteRig(SimpleNamespace(addCleanup=stack.callback), spec)
        world.rig = rig
        monkeypatch = stack.enter_context(pytest.MonkeyPatch.context())
        monkeypatch.setattr(
            native_runtime.LocalBlueStacksRuntime, "connect",
            lambda **kwargs: OfflineRuntime(kwargs["output_directory"]),
        )
        monkeypatch.setattr(training_native, "recognize_home", lambda *args, **kwargs: object())
        monkeypatch.setattr(training_native, "_canonical_home_proof", lambda *args: True)
        monkeypatch.setattr(
            training_native, "_training_return_to_home_after_preset",
            lambda *args: (None, None),
        )
        monkeypatch.setattr(training_native, "recognize_training_with_targets", recognize)
        route_type = training_native.TroopTrainingIntegratedRoute
        monkeypatch.setattr(
            training_native, "ensure_commander_talent_preset", saved_preset_observation,
        )
        monkeypatch.setattr(route_type, "run", enter_training)
        monkeypatch.setattr(route_type, "_switch_tab", switch_tab)
        monkeypatch.setattr(
            route_type, "_return_home",
            lambda route, source, *, status="completed", reason="recognized offline Home":
                route._result(status, reason, final_home=True),
        )
        yield world


def _reopened_training_state(world):
    store = SafetyStore(world.store_path)
    try:
        rows = store.list_actions_for_task(FLOW_ID)
    finally:
        store.close()
    binding = resource_fixed_runtime_binding()
    return rows, derive_training_action_state(
        rows,
        runtime_scope=binding.runtime_scope,
        account_id=binding.account_id,
        server_id=binding.server_id,
        game_day_id=recruitment_reset(world.rig.stop.now),
    )


def test_native_completed_and_active_visits_reach_real_service_projection(native_service):
    world = native_service
    rig = world.rig
    assert rig.once()
    first = world.payloads[-1]
    assert first["status"] == "completed"
    assert first["training_start_transport_calls"] == 4
    assert first["saved_training_preset_verified"] is True
    configs = world.routes[-1].config
    assert [
        (
            configs.for_type(troop).target_tier,
            configs.for_type(troop).quantity_mode,
            configs.for_type(troop).quantity,
            configs.for_type(troop).training_policy,
            configs.for_type(troop).allow_resource_boxes,
        )
        for troop in ("fighter", "vehicle", "shooter", "rider")
    ] == [
        (8, "current_max", None, "continuous", True),
        (1, "current_max", None, "continuous", True),
        (8, "fixed", 250, "once_daily", False),
        (1, "fixed", 250, "once_daily", False),
    ]
    assert all(mode == "active" for mode in world.modes.values())
    assert rig.runs()[-1].terminal_outcome == "complete_for_reset"
    from automation_service.troop_training import troop_training_next_due
    from scripts.navigation_development_boundary import RuntimeInputLock
    # Invoke the same real Runner with a fresh canonical lock: active visits
    # must project timers without requiring a native-side verification claim.
    with RuntimeInputLock(owner="automation-service", invocation_id="active-visit") as lock:
        result = rig.runner(
            _identity(rig.stop.now), None, lambda: None,
            runtime_input_lock=lock, occurrence_key="active-visit",
        )
    assert result["status"] == "completed"
    assert result["native_execution_verified"] is True
    assert result["training_dispatch_count"] == 0
    assert troop_training_next_due(result, _identity(rig.stop.now), rig.stop.now) == rig.stop.now + 3600
    assert len(world.inputs) == 4


def test_confirmed_claim_reopens_database_then_starts_next_continuous_generation(native_service):
    world = native_service
    rig = world.rig
    # Keep other configurations pending so the actual service schedules another
    # occurrence in this reset; all four fixed configurations remain intact.
    world.modes.update({troop: "shortage" for troop in ("vehicle", "shooter", "rider")})
    assert rig.once()
    rows, before = _reopened_training_state(world)
    first_start = before.pending_start_action_keys["fighter"]
    assert before.queue_generations["fighter"] == 1
    assert "fighter" not in before.next_start_action_keys
    assert len(rows) == 1
    assert world.payloads[-1]["status"] == "partial"
    assert set(world.payloads[-1]["remaining_eligible_variants"]) == {"vehicle", "shooter", "rider"}
    assert world.payloads[-1]["resource_box_dispatch_count"] == 0
    assert world.payloads[-1]["warehouse_dispatch_count"] == 0
    assert world.payloads[-1]["next_due_utc"] == rig.stop.now + 60
    # Same occurrence is durably consumed even when another service opens its DB.
    with BotStateManager(rig.path) as reopened:
        rig.once(reopened)
    assert len(world.inputs) == 1
    assert len(world.routes) == 1
    world.modes["fighter"] = "completed"
    rig.stop.now += 60
    with BotStateManager(rig.path) as reopened:
        assert rig.once(reopened)
    rows, after = _reopened_training_state(world)
    next_start = after.pending_start_action_keys["fighter"]
    assert next_start.endswith(":fighter:g2:start")
    assert next_start != first_start
    assert after.queue_generations["fighter"] == 2
    assert after.per_reset_variant_start_counts["fighter"] == 2
    assert after.per_reset_variant_claim_counts["fighter"] == 1
    assert world.inputs == [first_start, make_training_claim_action_key(first_start), next_start]
    assert len(rows) == 3
    assert all(row["final_status"] == "confirmed" for row in rows)
    assert world.payloads[-1]["claim_dispatch_count"] == 1
    assert world.payloads[-1]["training_start_transport_calls"] == 1
    assert world.payloads[-1]["committed_action_count"] == 2
    assert not world.payloads[-1]["effect_reconciliation_required"]
    assert world.routes[-1].controller.semantic.states["fighter"].queue_generation == 2


def test_uncertain_claim_cannot_mint_generation_or_repeat_after_reopen(native_service):
    world = native_service
    rig = world.rig
    world.modes.update({troop: "shortage" for troop in ("vehicle", "shooter", "rider")})
    rig.once()
    _, before = _reopened_training_state(world)
    first_start = before.pending_start_action_keys["fighter"]
    world.modes["fighter"] = "completed"
    world.uncertain_claim = True
    rig.stop.now += 60
    rig.once()
    rows, after = _reopened_training_state(world)
    assert world.inputs == [first_start, make_training_claim_action_key(first_start)]
    assert after.queue_generations["fighter"] == 1
    assert after.pending_start_action_keys["fighter"] == first_start
    assert "fighter" not in after.next_start_action_keys
    assert {row["final_status"] for row in rows} == {"confirmed", "unresolved"}
    assert world.payloads[-1]["effect_reconciliation_required"]
    assert world.payloads[-1]["identical_retry_denied"]
    assert "fighter" not in world.routes[-1].start_action_keys
    from scripts.navigation_development_boundary import RuntimeInputLock
    # Even a separate native invocation fails at the durable unresolved fence.
    with RuntimeInputLock(owner="automation-service", invocation_id="uncertain-reopen") as lock:
        result = rig.runner(
            _identity(rig.stop.now), None, lambda: None,
            runtime_input_lock=lock, occurrence_key="uncertain-reopen",
        )
    assert result["status"] == "blocked"
    assert "unresolved" in result["native_failure"]
    assert len(world.inputs) == 2
    assert len(world.routes) == 2


@pytest.mark.parametrize("troop", ("fighter", "vehicle"))
def test_claimed_continuous_batch_survives_shortage_and_reopen_before_next_start(native_service, troop):
    world = native_service
    rig = world.rig
    world.modes.update({other: "shortage" for other in TROOP_TYPES if other != troop})
    rig.once()
    _, before = _reopened_training_state(world)
    start = before.pending_start_action_keys[troop]
    world.modes[troop] = "completed"
    world.after_claim_mode = "shortage"
    rig.stop.now += 60
    with BotStateManager(rig.path) as reopened:
        rig.once(reopened)
    rows, claimed = _reopened_training_state(world)
    assert len(rows) == 2
    assert world.inputs == [start, make_training_claim_action_key(start)]
    assert troop not in claimed.pending_start_action_keys
    assert claimed.queue_generations[troop] == 1
    next_key = claimed.next_start_action_keys[troop]
    assert next_key.endswith(f":{troop}:g2:start")
    assert world.payloads[-1]["status"] == "partial"
    assert not world.payloads[-1]["effect_reconciliation_required"]
    world.modes[troop] = "empty"
    rig.stop.now += 60
    with BotStateManager(rig.path) as reopened:
        rig.once(reopened)
    rows, restarted = _reopened_training_state(world)
    assert len(rows) == 3
    assert all(row["final_status"] == "confirmed" for row in rows)
    assert world.inputs == [start, make_training_claim_action_key(start), next_key]
    assert restarted.queue_generations[troop] == 2
    assert restarted.pending_start_action_keys[troop] == next_key
    assert world.payloads[-1]["resource_box_dispatch_count"] == 0
    assert world.payloads[-1]["warehouse_dispatch_count"] == 0


@pytest.mark.parametrize("troop", ("fighter", "vehicle"))
@pytest.mark.parametrize("new_maximum", (613, 1427))
def test_reopened_batch_uses_authorized_quantity_then_next_start_reads_new_maximum(
    native_service, troop, new_maximum,
):
    from scripts.navigation_development_boundary import RuntimeInputLock

    world = native_service
    rig = world.rig
    world.modes.update({other: "shortage" for other in TROOP_TYPES if other != troop})
    assert rig.once()
    rows, first = _reopened_training_state(world)
    start = first.pending_start_action_keys[troop]
    assert first.prior_batch_quantities == {troop: 1000}
    assert rows[0]["quantity"] == 1000

    # The queue remains the old batch while the next batch's capacity changes.
    world.maxima[troop] = new_maximum
    with RuntimeInputLock(owner="automation-service", invocation_id="changed-max-active") as lock:
        result = rig.runner(
            _identity(rig.stop.now), None, lambda: None,
            runtime_input_lock=lock, occurrence_key="changed-max-active",
        )
    assert result["effect_reconciliation_required"] is False
    assert result["training_dispatch_count"] == 0
    assert world.inputs == [start]
    _, active = _reopened_training_state(world)
    assert active.prior_batch_quantities == {troop: 1000}

    world.modes[troop] = "completed"
    rig.stop.now += 60
    with BotStateManager(rig.path) as reopened:
        assert rig.once(reopened)
    rows, restarted = _reopened_training_state(world)
    next_start = restarted.pending_start_action_keys[troop]
    assert next_start.endswith(f":{troop}:g2:start")
    assert world.inputs == [start, make_training_claim_action_key(start), next_start]
    assert restarted.queue_generations[troop] == 2
    assert restarted.per_reset_variant_start_counts[troop] == 2
    assert restarted.per_reset_variant_claim_counts[troop] == 1
    assert restarted.prior_batch_quantities == {troop: new_maximum}
    assert {
        row["action_key"]: row["quantity"]
        for row in rows if row["semantic_action"] == "TROOP_TRAINING_START"
    } == {start: 1000, next_start: new_maximum}
    assert all(row["final_status"] == "confirmed" for row in rows)
    assert world.payloads[-1]["claim_dispatch_count"] == 1
    assert world.payloads[-1]["training_start_transport_calls"] == 1
    assert not world.payloads[-1]["effect_reconciliation_required"]


@pytest.mark.parametrize("changed_mode", ("active", "shortage"))
def test_changed_immediate_queue_or_cost_blocks_before_any_training_input(native_service, changed_mode):
    world = native_service
    world.pre_dispatch_mode = changed_mode
    assert world.rig.once()
    rows, state = _reopened_training_state(world)
    assert world.inputs == []
    assert rows == []
    assert all(count == 0 for count in state.per_reset_variant_start_counts.values())


@pytest.mark.parametrize("troop", ("fighter", "vehicle"))
@pytest.mark.parametrize("mode", ("active", "completed"))
def test_reopened_queue_quantity_must_match_durable_authorized_batch(native_service, troop, mode):
    world = native_service
    rig = world.rig
    world.modes.update({other: "shortage" for other in TROOP_TYPES if other != troop})
    assert rig.once()
    _, before = _reopened_training_state(world)
    start = before.pending_start_action_keys[troop]

    # Matching a new maximum is not proof that the persisted batch changed.
    world.maxima[troop] = 613
    world.queue_quantities[troop] = 613
    world.modes[troop] = mode
    rig.stop.now += 60
    with BotStateManager(rig.path) as reopened:
        assert rig.once(reopened)

    rows, after = _reopened_training_state(world)
    assert world.inputs == [start]
    assert len(rows) == 1
    assert rows[0]["final_status"] == "confirmed"
    assert after.pending_start_action_keys[troop] == start
    assert after.prior_batch_quantities == {troop: 1000}
    assert after.queue_generations[troop] == 1
    assert troop not in after.next_start_action_keys
    assert world.payloads[-1]["claim_dispatch_count"] == 0
    assert world.payloads[-1]["training_start_transport_calls"] == 0
