"""Focused tests for the canonical offline automation-service authority.

These tests deliberately use temporary SQLite databases and fake/replay seams.  They
prove that registration/evidence can describe a route, but only persisted SQLite
state can enable it or grant a dispatch fence.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
from io import StringIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from automation_service.adapters import FakeDeviceAdapter, FrameSample
from automation_service.cli import main
from automation_service.contracts import (
    FamilyFacts,
    FlowDescriptor,
    FlowSpec,
    NormalizedOutcome,
    NormalizedResult,
    PerceptionEnvelope,
    SchedulerFacts,
    ServiceMode,
)
from automation_service.registry import (
    CANONICAL_FLOW_REGISTRY,
    WORLD_FLOW_ID,
    WORLD_HANDLER_ID,
    WORLD_PHASE_MODE,
    WORLD_PRODUCT_ID,
    WORLD_PRODUCT_REVISION,
    WORLD_PROFILE_ID,
    load_disabled_registry,
)
from automation_service.scheduler import UtcPulseCoordinator
from automation_service.service import (
    AutomationService,
    ServiceError,
    legacy_registry_scheduler_components,
    registry_flow_spec,
    registry_scheduler_components,
)
from automation_service.state import ActionState, BotStateManager, RunState


FLOW_ID = "CANONICAL-FLOW"
RESET_ID = "reset-1"
PRODUCT_ID = "canonical-product"
PRODUCT_REVISION = "canonical-product-v1"
PROFILE_ID = "canonical-offline-profile"


def descriptor(
    flow_id: str = FLOW_ID,
    *,
    priority: int = 10,
) -> FlowDescriptor:
    return FlowDescriptor(
        flow_id=flow_id,
        owner="canonical-tests",
        family="offline-test",
        variant="selection-only",
        cadence="daily_once_per_reset",
        priority=priority,
        scheduler_eligible=True,
        accepted_product=PRODUCT_ID,
        product_revision=PRODUCT_REVISION,
        registration_status="REGISTERED",
    )


def facts(
    *,
    reset_id: str = RESET_ID,
    now: float = 100.0,
    **overrides: object,
) -> SchedulerFacts:
    values: dict[str, object] = {
        "health_ok": True,
        "accepted_product": PRODUCT_ID,
        "product_revision": PRODUCT_REVISION,
        "registration_status": "REGISTERED",
        "scheduler_eligible": True,
        "owner_available": True,
        "clock_ok": True,
        "reset_agreement": True,
    }
    values.update(overrides)
    return SchedulerFacts(
        "account",
        "server",
        reset_id,
        now,
        **values,
    )


def world_facts(*, now: float = 100.0, reset_id: str = RESET_ID) -> SchedulerFacts:
    return SchedulerFacts(
        "account",
        "server",
        reset_id,
        now,
        health_ok=True,
        accepted_product=WORLD_PRODUCT_ID,
        product_revision=WORLD_PRODUCT_REVISION,
        registration_status="REGISTERED",
        scheduler_eligible=True,
        owner_available=True,
        clock_ok=True,
        reset_agreement=True,
    )


def perception_with_evidence() -> PerceptionEnvelope:
    return PerceptionEnvelope(
        capture_id="capture-evidence",
        context="canonical-test",
        profile_id=WORLD_PROFILE_ID,
        freshness="current",
        family_facts=(
            FamilyFacts(
                "offline-test",
                recognized=True,
                values={"stable_source": "recognized", "target": "free"},
                source="native-frame",
            ),
        ),
    )


class ProbeHandler:
    """A zero-transport handler that exposes scheduler selection calls."""

    def __init__(self, flow_descriptor: FlowDescriptor) -> None:
        self.flow_descriptor = flow_descriptor
        self.plan_calls = 0

    def describe(self) -> FlowDescriptor:
        return self.flow_descriptor

    def eligibility(self, _facts: SchedulerFacts, _perception=None) -> bool:
        return True

    def revalidate(self, _facts: SchedulerFacts, _perception=None) -> bool:
        return True

    def plan(self, _facts: SchedulerFacts, _perception=None) -> NormalizedResult:
        self.plan_calls += 1
        return NormalizedResult(
            NormalizedOutcome.COMPLETE_FOR_RESET,
            "OFFLINE_SELECTION_COMPLETE",
            observed_progress={"transport_count": 0},
        )

    def reconcile(self, plan, _perception=None):
        return plan

    def recover(self, reason_code: str) -> NormalizedResult:
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason_code)

    def summarize(self):
        return {"flow_id": self.flow_descriptor.flow_id, "plan_calls": self.plan_calls}


def world_registry_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "registry_kind": "disabled_production_handlers",
        "flows": {
            WORLD_FLOW_ID: {
                "production_handler": WORLD_HANDLER_ID,
                "profile": WORLD_PROFILE_ID,
                "supported_profiles": [WORLD_PROFILE_ID],
                "mode": WORLD_PHASE_MODE,
                "registration_status": "REGISTERED",
                "scheduler_eligible": True,
                "product_id": WORLD_PRODUCT_ID,
                "product_revision": WORLD_PRODUCT_REVISION,
            }
        },
    }


def write_world_registry(folder: str | Path) -> Path:
    path = Path(folder) / "registry.json"
    path.write_text(json.dumps(world_registry_payload(), sort_keys=True), encoding="utf-8")
    return path


def initialize_manager(
    path: Path,
    flow_specs: list[FlowSpec],
    *,
    owner: str = "owner-a",
) -> BotStateManager:
    manager = BotStateManager(
        path,
        owner_instance_id=owner,
        process_start_token=f"{owner}-process",
        process_id=101,
    )
    manager.initialize_flows(flow_specs)
    manager.set_service_enabled(True, now_utc_epoch=0.0)
    for spec in flow_specs:
        manager.set_flow_enabled(spec.flow_id, True, now_utc_epoch=0.0)
    lease = manager.acquire_service_lease(
        owner_instance_id=owner,
        process_start_token=f"{owner}-process",
        process_id=101,
        lease_ttl_seconds=1_000.0,
        now_utc_epoch=0.0,
    )
    if lease is None:
        raise AssertionError("test manager failed to acquire deterministic service lease")
    return manager


def lease_auth(manager: BotStateManager) -> dict[str, object]:
    lease = manager.get_service_lease()
    if lease.lease_generation < 1:
        raise AssertionError("test manager has no service lease")
    return {
        "owner_instance_id": manager.owner_instance_id,
        "process_start_token": manager.process_start_token,
        "lease_generation": lease.lease_generation,
    }


def run_auth(run) -> dict[str, object]:
    return {
        "owner_instance_id": run.owner_instance_id,
        "process_start_token": run.process_start_token,
        "run_token": run.run_token,
        "lease_generation": run.lease_generation,
    }


class CanonicalAutomationAuthorityTests(unittest.TestCase):
    def test_static_flow_specs_and_registered_descriptors_initialize_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            registry_path = write_world_registry(folder)
            manager = BotStateManager(Path(folder) / "state.sqlite3")
            try:
                (entry,) = load_disabled_registry(registry_path)
                spec = registry_flow_spec(entry)
                self.assertFalse(spec.default_enabled)
                self.assertTrue(entry.registered)

                states = manager.initialize_flows(
                    [FlowSpec(FLOW_ID, default_enabled=True, priority=3)]
                )
                self.assertEqual(len(states), 1)
                self.assertFalse(states[0].enabled)

                registered_states = manager.initialize_flows([spec])
                self.assertEqual(len(registered_states), 1)
                self.assertFalse(registered_states[0].enabled)
                self.assertEqual(manager.get_service().generation, 0)
            finally:
                manager.close()

    def test_sqlite_is_sole_enable_authority_registry_environment_and_evidence_cannot_enable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            registry_path = write_world_registry(folder)
            registry_before = registry_path.read_bytes()
            state_path = Path(folder) / "state.sqlite3"
            manager = BotStateManager(state_path, owner_instance_id="owner-a")
            try:
                entries, descriptors, _handlers, coordinator = registry_scheduler_components(
                    manager
                )
                self.assertEqual(
                    [entry.flow_id for entry in entries],
                    [entry.flow_id for entry in CANONICAL_FLOW_REGISTRY],
                )
                self.assertEqual(
                    [descriptor.flow_id for descriptor in descriptors],
                    [entry.flow_id for entry in CANONICAL_FLOW_REGISTRY],
                )
                self.assertTrue(
                    all(descriptor.scheduler_eligible for descriptor in descriptors)
                )
                self.assertFalse(manager.get_flow_enabled(WORLD_FLOW_ID))
                self.assertFalse(manager.get_service_enabled())

                report = coordinator.shadow(
                    world_facts(),
                    perception=perception_with_evidence(),
                    flow_id=WORLD_FLOW_ID,
                )
                self.assertIsNone(report.candidate)
                self.assertEqual(report.reason_code, "SERVICE_DISABLED")
                self.assertFalse(manager.get_flow_enabled(WORLD_FLOW_ID))
                self.assertEqual(registry_path.read_bytes(), registry_before)
            finally:
                manager.close()

            output = StringIO()
            with patch.dict(
                os.environ,
                {
                    "AUTOMATION_SERVICE_MODE": "dry_run",
                    "AUTOMATION_SERVICE_ADAPTER": "fake",
                },
                clear=False,
            ), contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(["--state-path", str(state_path), "status"]),
                    0,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["mode"], "dry_run")
            self.assertFalse(payload["service_enabled"])
            self.assertFalse(payload["flow_enabled"][WORLD_FLOW_ID])
            self.assertEqual(
                set(payload["flow_enabled"]),
                {entry.flow_id for entry in CANONICAL_FLOW_REGISTRY},
            )

    def test_service_and_flow_gates_refuse_manual_live_execution_until_both_sqlite_gates_open(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            registry_path = write_world_registry(folder)
            state = BotStateManager(Path(folder) / "state.sqlite3", owner_instance_id="owner-a")
            try:
                _entries, _descriptors, _handlers, coordinator = registry_scheduler_components(
                    state
                )
                service = AutomationService(
                    mode=ServiceMode.DRY_RUN,
                    adapter=FakeDeviceAdapter(),
                    coordinator=coordinator,
                    state=state,
                )

                with self.assertRaisesRegex(ServiceError, "SERVICE_DISABLED"):
                    service.run(WORLD_FLOW_ID, world_facts(), live=True)

                state.set_service_enabled(True, now_utc_epoch=101.0)
                with self.assertRaisesRegex(ServiceError, "FLOW_DISABLED"):
                    service.run(WORLD_FLOW_ID, world_facts(now=102.0), live=True)

                state.set_flow_enabled(WORLD_FLOW_ID, True, now_utc_epoch=103.0)
                report = service.run(WORLD_FLOW_ID, world_facts(now=104.0), live=True)
                self.assertIsNotNone(report.candidate)
                self.assertEqual(report.result.reason_code, "WORLD_NAVIGATION_PARENT_CANARY_REQUIRED")
                self.assertEqual(report.result.observed_progress["transport_count"], 0)
            finally:
                state.close()
    def test_observe_is_structurally_zero_input(self) -> None:
        envelope = PerceptionEnvelope(
            capture_id="frame-1",
            context="home",
            profile_id=PROFILE_ID,
            freshness="current",
        )
        adapter = FakeDeviceAdapter([FrameSample("frame-1", envelope)])
        service = AutomationService(mode=ServiceMode.OBSERVE_ONLY, adapter=adapter)

        sample = service.observe()
        self.assertEqual(sample.frame_id, "frame-1")
        self.assertEqual(sample.envelope, envelope)
        self.assertEqual(adapter.attempted_intents, ())
        self.assertEqual(adapter.status().transport_count, 0)

    def test_shadow_selection_is_mutation_free(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            state = initialize_manager(
                path,
                [FlowSpec(FLOW_ID, default_enabled=True, priority=4)],
            )
            flow_descriptor = descriptor()
            handler = ProbeHandler(flow_descriptor)
            coordinator = UtcPulseCoordinator(
                state,
                [flow_descriptor],
                {FLOW_ID: handler},
            )
            try:
                service_before = state.get_service()
                flow_before = state.get_flow(FLOW_ID)
                self.assertIsNotNone(flow_before)
                with contextlib.closing(sqlite3.connect(path)) as connection:
                    before_counts = tuple(
                        connection.execute(
                            "SELECT (SELECT COUNT(*) FROM runs), (SELECT COUNT(*) FROM actions)"
                        ).fetchone()
                    )

                selected = coordinator.select(facts())
                shadow = coordinator.shadow(facts())

                self.assertIsNotNone(selected)
                self.assertIsNone(selected.claim)
                self.assertEqual(shadow.reason_code, "SHADOW_CANDIDATE")
                self.assertIsNotNone(shadow.candidate)
                self.assertIsNone(shadow.candidate.claim)
                self.assertEqual(handler.plan_calls, 0)
                self.assertEqual(state.get_service(), service_before)
                self.assertEqual(state.get_flow(FLOW_ID), flow_before)
                with contextlib.closing(sqlite3.connect(path)) as connection:
                    after_counts = tuple(
                        connection.execute(
                            "SELECT (SELECT COUNT(*) FROM runs), (SELECT COUNT(*) FROM actions)"
                        ).fetchone()
                    )
                self.assertEqual(after_counts, before_counts)
                self.assertEqual(after_counts, (0, 0))
            finally:
                state.close()

    def test_occurrence_key_is_deterministic_and_reset_scoped(self) -> None:
        self.assertEqual(
            BotStateManager.occurrence_key(FLOW_ID, RESET_ID, 7),
            f"{FLOW_ID}:{RESET_ID}:7",
        )
        self.assertEqual(
            BotStateManager.occurrence_key(FLOW_ID, RESET_ID, 7),
            BotStateManager.occurrence_key(FLOW_ID, RESET_ID, 7),
        )
        self.assertNotEqual(
            BotStateManager.occurrence_key(FLOW_ID, RESET_ID, 7),
            BotStateManager.occurrence_key(FLOW_ID, RESET_ID, 8),
        )
        self.assertNotEqual(
            BotStateManager.occurrence_key(FLOW_ID, RESET_ID, 7),
            BotStateManager.occurrence_key(FLOW_ID, "reset-2", 7),
        )

        with tempfile.TemporaryDirectory() as folder:
            manager = initialize_manager(
                Path(folder) / "state.sqlite3",
                [FlowSpec(FLOW_ID, default_enabled=True)],
            )
            try:
                first = manager.claim_occurrence(
                    FLOW_ID,
                    RESET_ID,
                    now_utc_epoch=100.0,
                    **lease_auth(manager),
                )
                self.assertIsNotNone(first)
                self.assertEqual(first.occurrence_key, f"{FLOW_ID}:{RESET_ID}:0")
                self.assertIsNotNone(
                    manager.transition_run(
                        first.run_id,
                        RunState.RUNNING,
                        **run_auth(first),
                        now_utc_epoch=101.0,
                    )
                )
                self.assertIsNotNone(
                    manager.transition_run(
                        first.run_id,
                        RunState.SUCCEEDED,
                        **run_auth(first),
                        now_utc_epoch=102.0,
                    )
                )
                next_occurrence = manager.claim_occurrence(
                    FLOW_ID,
                    RESET_ID,
                    now_utc_epoch=103.0,
                    **lease_auth(manager),
                )
                self.assertIsNotNone(next_occurrence)
                self.assertEqual(next_occurrence.occurrence_key, f"{FLOW_ID}:{RESET_ID}:1")
            finally:
                manager.close()

    def test_max_wait_bounds_starvation_of_lower_priority_flow(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            state = initialize_manager(
                path,
                [
                    FlowSpec("HIGH", default_enabled=True, priority=1),
                    FlowSpec(
                        "LOW",
                        default_enabled=True,
                        priority=99,
                        max_wait_seconds=10.0,
                    ),
                ],
            )
            high_descriptor = descriptor("HIGH", priority=1)
            low_descriptor = descriptor("LOW", priority=99)
            coordinator = UtcPulseCoordinator(
                state,
                [high_descriptor, low_descriptor],
                {
                    "HIGH": ProbeHandler(high_descriptor),
                    "LOW": ProbeHandler(low_descriptor),
                },
            )
            try:
                candidate = coordinator.select(facts(now=11.0))
                self.assertIsNotNone(candidate)
                self.assertEqual(candidate.descriptor.flow_id, "LOW")
                self.assertEqual(candidate.occurrence_key, "LOW:reset-1:0")
            finally:
                state.close()

    def test_emergency_generation_invalidates_active_pre_dispatch_fence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = initialize_manager(
                Path(folder) / "state.sqlite3",
                [FlowSpec(FLOW_ID, default_enabled=True)],
            )
            try:
                run = state.claim_occurrence(
                    FLOW_ID,
                    RESET_ID,
                    now_utc_epoch=100.0,
                    max_inputs=1,
                    max_actions=1,
                    **lease_auth(state),
                )
                self.assertIsNotNone(run)
                self.assertIsNotNone(
                    state.transition_run(
                        run.run_id,
                        RunState.RUNNING,
                        **run_auth(run),
                        now_utc_epoch=101.0,
                    )
                )
                action = state.reserve_action(
                    run.run_id,
                    "before-emergency",
                    "offline-test-input",
                    action_id="action-before-emergency",
                    **run_auth(run),
                    now_utc_epoch=102.0,
                )
                self.assertIsNotNone(action)
                before_generation = state.get_service().generation

                stopped = state.set_service_enabled(
                    False,
                    emergency_reason="test emergency",
                    now_utc_epoch=103.0,
                )
                self.assertEqual(stopped.generation, before_generation + 1)
                self.assertEqual(state.get_run(run.run_id).state, RunState.STOP_REQUESTED)
                self.assertEqual(
                    state.validate_dispatch(run.run_id, now_utc_epoch=104.0).reason,
                    "SERVICE_DISABLED",
                )
                self.assertIsNone(
                    state.transition_action(
                        action.action_id,
                        ActionState.DISPATCHING,
                        expected_state=ActionState.RESERVED,
                        **run_auth(run),
                        now_utc_epoch=104.0,
                    )
                )
                self.assertEqual(state.get_action(action.action_id).state, ActionState.RESERVED)
            finally:
                state.close()
    def test_one_active_claim_is_global_and_releases_after_terminal_transition(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            state = initialize_manager(
                Path(folder) / "state.sqlite3",
                [
                    FlowSpec("FIRST", default_enabled=True, priority=1),
                    FlowSpec("SECOND", default_enabled=True, priority=2),
                ],
            )
            try:
                first = state.claim_occurrence(
                    "FIRST",
                    RESET_ID,
                    now_utc_epoch=100.0,
                    **lease_auth(state),
                )
                self.assertIsNotNone(first)
                self.assertIsNone(
                    state.claim_occurrence(
                        "SECOND",
                        RESET_ID,
                        now_utc_epoch=101.0,
                        **lease_auth(state),
                    )
                )
                self.assertIsNotNone(
                    state.transition_run(
                        first.run_id,
                        RunState.RUNNING,
                        **run_auth(first),
                        now_utc_epoch=102.0,
                    )
                )
                self.assertIsNotNone(
                    state.transition_run(
                        first.run_id,
                        RunState.SUCCEEDED,
                        **run_auth(first),
                        now_utc_epoch=103.0,
                    )
                )
                lease_before_release = lease_auth(state)
                self.assertTrue(state.release_service_lease(**lease_before_release))
                self.assertFalse(state.release_service_lease(**lease_before_release))
                reacquired = state.acquire_service_lease(
                    owner_instance_id=state.owner_instance_id,
                    process_start_token=state.process_start_token,
                    process_id=state.process_id,
                    lease_ttl_seconds=1_000.0,
                    now_utc_epoch=104.0,
                )
                self.assertIsNotNone(reacquired)
                assert reacquired is not None
                self.assertGreater(reacquired.lease_generation, lease_before_release["lease_generation"])
                second = state.claim_occurrence(
                    "SECOND",
                    RESET_ID,
                    now_utc_epoch=105.0,
                    **lease_auth(state),
                )
                self.assertIsNotNone(second)
            finally:
                state.close()

    def test_canonical_state_manager_rejects_legacy_paths_and_uses_static_registry(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            registry_path = write_world_registry(folder)
            state = BotStateManager(Path(folder) / "state.sqlite3", owner_instance_id="owner-a")
            disabled = {
                "mode": "disabled",
                "product_id": None,
                "product_revision": None,
                "production_handler": None,
                "profile": None,
                "registration_status": "NOT_REGISTERED",
                "scheduler_eligible": False,
                "supported_profiles": [],
            }
            suppressed = world_registry_payload()
            added = world_registry_payload()
            added["flows"]["UNTRUSTED-FLOW"] = disabled
            rebound = world_registry_payload()
            rebound["flows"][WORLD_FLOW_ID]["production_handler"] = "untrusted-handler"
            payloads = (
                json.dumps(suppressed, sort_keys=True).encode(),
                json.dumps(added, sort_keys=True).encode(),
                json.dumps(rebound, sort_keys=True).encode(),
                b"not a registry",
            )
            try:
                for payload in payloads:
                    registry_path.write_bytes(payload)
                    with self.assertRaisesRegex(
                        ValueError, "canonical scheduler rejects legacy registry path"
                    ):
                        registry_scheduler_components(state, path=registry_path)
                    with self.assertRaisesRegex(
                        ValueError, "legacy registry composition cannot use BotStateManager"
                    ):
                        legacy_registry_scheduler_components(
                            state, path=registry_path
                        )
                    with self.assertRaisesRegex(
                        ValueError, "canonical scheduler rejects legacy registry path"
                    ):
                        registry_scheduler_components(
                            state_manager=state, path=registry_path
                        )
                    self.assertEqual(registry_path.read_bytes(), payload)

                    entries, descriptors, _handlers, coordinator = (
                        registry_scheduler_components(state)
                    )
                    self.assertIs(entries, CANONICAL_FLOW_REGISTRY)
                    self.assertEqual(
                        tuple(item.flow_id for item in entries),
                        tuple(item.flow_id for item in CANONICAL_FLOW_REGISTRY),
                    )
                    self.assertEqual(
                        tuple(item.flow_id for item in descriptors),
                        tuple(item.flow_id for item in CANONICAL_FLOW_REGISTRY),
                    )
                    self.assertIsNone(coordinator.activation_authority)
                    self.assertEqual(
                        {
                            item.flow_id
                            for item in CANONICAL_FLOW_REGISTRY
                            if state.get_flow(item.flow_id) is not None
                        },
                        {item.flow_id for item in CANONICAL_FLOW_REGISTRY},
                    )

                state.set_service_enabled(True, now_utc_epoch=100.0)
                state.set_flow_enabled(WORLD_FLOW_ID, True, now_utc_epoch=100.0)
                status = AutomationService(
                    mode=ServiceMode.DRY_RUN,
                    adapter=FakeDeviceAdapter(),
                    state=state,
                ).status()
                self.assertEqual(
                    status.registered_flows,
                    tuple(item.flow_id for item in CANONICAL_FLOW_REGISTRY),
                )
                self.assertTrue(status.service_enabled)
                self.assertTrue(status.flow_enabled[WORLD_FLOW_ID])
                self.assertEqual(registry_path.read_bytes(), payloads[-1])
            finally:
                state.close()

    def test_canonical_modules_have_no_forbidden_governance_import_boundary(self) -> None:
        package = Path(__file__).resolve().parents[1] / "automation_service"
        forbidden = (
            "flow_delivery_control",
            "backlog",
            "current_handoff",
            "flow_delivery_queue",
            "delegated",
            "git",
        )
        for source_path in sorted(package.glob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            imported_modules: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules.append(node.module)
            for module in imported_modules:
                lowered = module.casefold()
                self.assertFalse(
                    any(token in lowered for token in forbidden),
                    f"{source_path.name} imports forbidden governance authority {module!r}",
                )


if __name__ == "__main__":
    unittest.main()
