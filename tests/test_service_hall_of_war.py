from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from automation_service.hall_of_war import (
    FLOW_ID,
    MAX_INPUTS,
    PRODUCT_ID,
    HallOfWarRunner,
    _backend_identity_mapping,
    hall_of_war_next_due,
)
from automation_service.native_execution import NativeRouteOutcome
from automation_service.recruitment import recruitment_reset
from tasks.runtime_identity import resource_fixed_runtime_binding
from tasks.scheduler_task_result import SchedulerIdentity
from automation_service.state import BotStateManager
from tests.support.service_route_contract import ROUTES, RouteRig


class FakeBoundary:
    flow_id = FLOW_ID

    def __init__(self, native_result, *, failure=None, partial_result=None, input_count=None):
        self.native_result = native_result
        self.failure = failure
        self.partial_result = partial_result
        self.input_count = (
            native_result.get("total_input_count", 0) if input_count is None else input_count
        )
        self.request = None

    def run(self, request):
        self.request = request
        return NativeRouteOutcome(
            flow_id=FLOW_ID,
            native_result=self.native_result,
            partial_result=self.partial_result,
            failure=self.failure,
            invocation_id="hall-of-war-test-invocation",
            session_directory="native-session",
            startup_recovery=None,
            input_count=self.input_count,
            session_input_count=self.input_count,
            runtime_input_count=self.input_count,
            accounting_verified=True,
        )


def _fixture_result(now, identity):
    from tasks.runtime_identity import derive_resource_runtime_identity

    binding = resource_fixed_runtime_binding()
    backend = derive_resource_runtime_identity(
        binding, datetime.fromtimestamp(now, timezone.utc)
    )
    return {
        "status": "deferred",
        "challenge_status": "busy",
        "reward_status": "unavailable",
        "dispatch_transport_calls": 0,
        "reward_claim_transport_calls": 0,
        "talent_switch_transport_calls": 0,
        "hall_of_war_dispatch_count": 0,
        "committed_action_count": 0,
        "effect_reconciliation_required": False,
        "identical_retry_denied": False,
        "accounting_verified": True,
        "terminal_home_verified": True,
        "scheduler_reset_id": identity.reset_id,
        "backend_identity_proof": _backend_identity_mapping(backend),
        "total_input_count": 5,
    }


def _identity(now):
    binding = resource_fixed_runtime_binding()
    return SchedulerIdentity(
        binding.account_id,
        binding.server_id,
        recruitment_reset(now),
        PRODUCT_ID,
    )

@pytest.mark.parametrize("operator_request_id", (None, "owner-supervised-hall-canary"))
def test_claimed_manual_request_reaches_only_matching_native_occurrence(tmp_path, operator_request_id):
    now = datetime(2025, 1, 2, 12, tzinfo=timezone.utc).timestamp()
    identity = _identity(now)
    boundary = FakeBoundary(_fixture_result(now, identity))
    runner = HallOfWarRunner(
        native=boundary, output_directory=tmp_path,
        utc_clock=lambda: now, monotonic_clock=lambda: 10.0,
    )
    result = runner(
        identity, None, lambda: None, runtime_input_lock=object(),
        occurrence_key="claimed-hall-occurrence", operator_request_id=operator_request_id,
    )
    assert result["status"] == "deferred"
    assert dict(boundary.request.arguments) == (
        {} if operator_request_id is None else {
            "operator_request_id": operator_request_id,
            "manual_occurrence_key": "claimed-hall-occurrence",
        }
    )


@pytest.mark.parametrize("operator_request_id", ("", " ", " request ", True, "x" * 257))
def test_invalid_manual_request_never_enters_native_boundary(tmp_path, operator_request_id):
    now = datetime(2025, 1, 2, 12, tzinfo=timezone.utc).timestamp()
    identity = _identity(now)
    boundary = FakeBoundary(_fixture_result(now, identity))
    result = HallOfWarRunner(
        native=boundary, output_directory=tmp_path, utc_clock=lambda: now,
    )(
        identity, None, lambda: None, runtime_input_lock=object(),
        occurrence_key="claimed-hall-occurrence", operator_request_id=operator_request_id,
    )
    assert result["status"] == "blocked"
    assert boundary.request is None
    assert result["dispatch_transport_calls"] == 0




@pytest.mark.parametrize(
    ("confirmed_challenge", "seconds_before_reset", "manual_use"),
    ((False, 3600, False), (True, 3600, False), (False, 1, False), (False, 3600, True)),
)
def test_known_deferral_preserves_progress_and_reopen_waits_before_reset(
    confirmed_challenge, seconds_before_reset, manual_use,
):
    with ExitStack() as stack:
        native_visits = []

        def make_runner(stop, root):
            day = datetime.fromtimestamp(stop.now, timezone.utc)
            deadline = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 86400
            stop.now = deadline - seconds_before_reset
            payload = _fixture_result(stop.now, _identity(stop.now))
            if confirmed_challenge:
                payload.update(
                    challenge_status="confirmed",
                    dispatch_transport_calls=1,
                    hall_of_war_dispatch_count=1,
                    committed_action_count=1,
                )
            if manual_use:
                payload.update(
                    challenge_status="deferred_unexplained_prior_same_reset_use",
                    challenge_participation_proven=True,
                    today_highest_damage=321,
                )

            class ObservedBoundary(FakeBoundary):
                def run(self, request):
                    native_visits.append(request.occurrence_key)
                    return super().run(request)

            return HallOfWarRunner(
                native=ObservedBoundary(payload),
                output_directory=root / "native-sessions",
                utc_clock=lambda: stop.now,
                monotonic_clock=lambda: 10.0,
            )

        spec = replace(ROUTES[FLOW_ID], make_runner=make_runner)
        rig = RouteRig(SimpleNamespace(addCleanup=stack.callback), spec)
        started = rig.stop.now
        rig.once()
        first = rig.runs()[-1]
        flow = rig.state.get_flow(FLOW_ID)
        assert first.state.value == "DEFERRED"
        assert first.consumed_actions == int(confirmed_challenge)
        assert flow.blocked is False
        deadline = datetime.fromtimestamp(started, timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).timestamp() + 86400
        assert started < flow.next_due_at_utc <= deadline
        rig.stop.now = flow.next_due_at_utc - 0.25
        with BotStateManager(rig.path) as reopened:
            rig.once(reopened)
        assert [run.run_id for run in rig.runs()] == [first.run_id]
        assert native_visits == [first.occurrence_key]

def test_unknown_native_transport_effect_returns_retained_mapping_without_retry(tmp_path):
    now = datetime(2025, 1, 2, 12, tzinfo=timezone.utc).timestamp()
    identity = _identity(now)
    partial = {
        "status": "unresolved",
        "dispatch_transport_calls": 1,
        "reward_claim_transport_calls": 0,
        "talent_switch_transport_calls": 0,
        "hall_of_war_dispatch_count": 1,
        "committed_action_count": 0,
        "effect_reconciliation_required": True,
        "identical_retry_denied": True,
        "input_count": 1,
        "total_input_count": 1,
    }
    boundary = FakeBoundary(
        partial,
        failure="native transport response was lost",
        partial_result=partial,
        input_count=1,
    )
    runner = HallOfWarRunner(
        native=boundary,
        output_directory=Path(tmp_path),
        utc_clock=lambda: now,
        monotonic_clock=lambda: 10.0,
    )
    occurrence_key = " opaque hall occurrence "
    result = runner(
        identity,
        None,
        lambda: None,
        runtime_input_lock=object(),
        occurrence_key=occurrence_key,
    )
    assert isinstance(result, dict)
    assert result["status"] == "unresolved"
    assert result["dispatch_transport_calls"] == result["hall_of_war_dispatch_count"] == 1
    assert result["committed_action_count"] == 0
    assert result["effect_reconciliation_required"] is True
    assert result["identical_retry_denied"] is True
    assert result["occurrence_key"] == occurrence_key
    assert boundary.request.occurrence_key == occurrence_key
    assert hall_of_war_next_due(result, identity, now - 1) is None


def test_missing_native_boundary_returns_blocked_mapping_without_claiming_actions(tmp_path):
    now = datetime(2025, 1, 2, 12, tzinfo=timezone.utc).timestamp()
    identity = _identity(now)
    result = HallOfWarRunner(
        native=None,
        output_directory=Path(tmp_path),
        utc_clock=lambda: now,
    )(
        identity,
        None,
        lambda: None,
        runtime_input_lock=object(),
        occurrence_key="missing-native-hall",
    )
    assert result["status"] == "blocked"
    assert result["dispatch_transport_calls"] == result["reward_claim_transport_calls"] == 0
    assert result["hall_of_war_dispatch_count"] == result["committed_action_count"] == 0
    assert result["accounting_verified"] is False
