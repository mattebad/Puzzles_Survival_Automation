from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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




def _identity(now: float) -> SchedulerIdentity:
    binding = resource_fixed_runtime_binding()
    return SchedulerIdentity(
        binding.account_id,
        binding.server_id,
        recruitment_reset(now),
        PRODUCT_ID,
    )


def _row(action_key: str, *, reset_id: str, status: str, semantic_action: str) -> dict[str, object]:
    return {
        "task_id": FLOW_ID,
        "action_key": action_key,
        "final_status": status,
        "game_day_id": reset_id,
        "semantic_action": semantic_action,
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
    assert state.next_start_action_keys["fighter"].endswith(":fighter:g2:start")
    assert "vehicle" in state.blocked_start_variants
    assert "vehicle" not in state.next_start_action_keys


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
