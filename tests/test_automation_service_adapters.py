from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from safe_action_core import (
    ExecutionResult,
    InputCapability,
    PolicyRequest,
    SafeActionExecutor,
)
from safe_action_core.models import (
    ActionClass,
    ActionStatus,
    CapabilityAuthorityBinding,
    Observation,
)
from automation_service.adapters import (
    AdapterError,
    AdmissionToken,
    FakeDeviceAdapter,
    FrameSample,
    ReplayDeviceAdapter,
    SupervisedBlueStacksAdapter,
)
from automation_service.contracts import PerceptionEnvelope, SemanticActionIntent, ServiceMode


def sample(name: str = "frame") -> FrameSample:
    return FrameSample(
        name,
        PerceptionEnvelope(name, "home_canonical", "profile", "fresh"),
    )


def executor() -> SafeActionExecutor:
    return SafeActionExecutor(
        store=Mock(),
        policy=Mock(),
        owner_id="owner",
        monotonic_clock=lambda: 1.0,
        transport=Mock(),
        recapture=Mock(),
        post_observe=Mock(),
        reconcile=Mock(),
    )


def core_authority(
    *,
    task_id: str = "flow",
    semantic_action: str = "named_action",
    action_class: ActionClass = ActionClass.NAVIGATION_ONLY,
) -> tuple[PolicyRequest, InputCapability]:
    observation = Observation(
        frame_sha256="a" * 64,
        capture_completed_monotonic=1.0,
        runtime_profile_id="profile",
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="HOME_BASE",
        overlay_state="none",
        target_identity="target",
        target_roi=(1, 1, 10, 10),
        consequence="navigate_zero_cost",
        expected_postcondition="SUCCESSOR",
    )
    request = PolicyRequest(
        action_id="action",
        action_key="action-key",
        task_id=task_id,
        task_mode="supervised",
        semantic_action=semantic_action,
        expected_runtime_profile_id="profile",
        observation=observation,
        monotonic_now=1.0,
        observation_max_age_seconds=3.0,
        dispatch_max_age_seconds=3.0,
        lease_owner="owner",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        action_class=action_class,
        runtime_session_id="session",
    )
    binding = CapabilityAuthorityBinding(
        task_id=task_id,
        runtime_session_id="session",
        action_class=action_class,
        action_id=request.action_id,
        action_key=request.action_key,
        semantic_action=semantic_action,
        target_identity="target",
        capture_frame_sha256="a" * 64,
        capture_completed_monotonic=1.0,
        runtime_profile_id="profile",
        width=800,
        height=1280,
        target_roi=(1, 1, 10, 10),
    )
    capability = object.__new__(InputCapability)
    object.__setattr__(capability, "_binding", binding)
    return request, capability


def token(**overrides) -> AdmissionToken:
    values = {
        "flow_id": "flow",
        "task_id": "flow",
        "semantic_action": "named_action",
        "action_class": ActionClass.NAVIGATION_ONLY.value,
        "issued_at_utc": 10.0,
        "expires_at_utc": 20.0,
    }
    values.update(overrides)
    return AdmissionToken(**values)


class AutomationServiceAdapterTests(unittest.TestCase):
    def test_fake_and_replay_adapters_never_transport(self) -> None:
        intent = SemanticActionIntent("observe", "flow", "home", "home")
        for adapter in (FakeDeviceAdapter((sample(),)), ReplayDeviceAdapter((sample(),))):
            self.assertEqual(adapter.capture().frame_id, "frame")
            self.assertFalse(adapter.execute(intent))
            self.assertEqual(adapter.status().transport_count, 0)

    def test_supervised_adapter_requires_token_and_rejects_non_supervised_mode(self) -> None:
        with self.assertRaises(AdapterError):
            SupervisedBlueStacksAdapter(
                admission_token=token(),
                capture=lambda: sample(),
                executor=executor(),
                request_capability_binding=Mock(),
                connection_status=lambda: True,
                mode=ServiceMode.DRY_RUN,
            )
        with self.assertRaises(AdapterError):
            SupervisedBlueStacksAdapter(
                admission_token=token(),
                capture=lambda: sample(),
                executor=Mock(),
                request_capability_binding=Mock(),
                connection_status=lambda: True,
            )

    def test_supervised_adapter_dispatches_only_through_executor(self) -> None:
        safe_executor = executor()
        binding = Mock()
        binding.bind.return_value = core_authority()
        adapter = SupervisedBlueStacksAdapter(
            admission_token=token(),
            capture=lambda: sample("supervised"),
            executor=safe_executor,
            request_capability_binding=binding,
            connection_status=lambda: True,
            utc_clock=lambda: 11.0,
        )
        intent = SemanticActionIntent("named_action", "flow", "home", "successor", flow_id="flow")
        with patch.object(
            SafeActionExecutor,
            "execute",
            return_value=ExecutionResult("action", ActionStatus.CONFIRMED, "ok", 1),
        ) as execute:
            result = adapter.execute(intent)
        self.assertEqual(result.transport_calls, 1)
        execute.assert_called_once()
        self.assertEqual(adapter.status().transport_count, 1)
        self.assertTrue(adapter.status().connected)

    def test_supervised_adapter_rejects_mismatch_expiry_reuse_and_transport_parameter(self) -> None:
        with self.assertRaises(TypeError):
            SupervisedBlueStacksAdapter(
                admission_token=token(),
                capture=lambda: sample(),
                transport=lambda _intent: None,
            )
        for now, intent in (
            (11.0, SemanticActionIntent("other", "flow", "home", "successor", flow_id="flow")),
            (21.0, SemanticActionIntent("named_action", "flow", "home", "successor", flow_id="flow")),
        ):
            adapter = SupervisedBlueStacksAdapter(
                admission_token=token(),
                capture=lambda: sample(),
                executor=executor(),
                request_capability_binding=Mock(),
                connection_status=lambda: False,
                utc_clock=lambda now=now: now,
            )
            with self.assertRaises(AdapterError):
                adapter.execute(intent)
        binding = Mock()
        binding.bind.return_value = core_authority()
        safe_executor = executor()
        adapter = SupervisedBlueStacksAdapter(
            admission_token=token(),
            capture=lambda: sample(),
            executor=safe_executor,
            request_capability_binding=binding,
            connection_status=lambda: True,
            utc_clock=lambda: 11.0,
        )
        intent = SemanticActionIntent("named_action", "flow", "home", "successor", flow_id="flow")
        with patch.object(
            SafeActionExecutor,
            "execute",
            return_value=ExecutionResult("action", ActionStatus.CONFIRMED, "ok", 1),
        ):
            adapter.execute(intent)
        with self.assertRaises(AdapterError):
            adapter.execute(intent)

    def test_supervised_adapter_rejects_request_and_capability_impersonation(self) -> None:
        request, capability = core_authority()
        for bound in (
            (replace(request, task_id="other"), capability),
            (
                request,
                core_authority(semantic_action="other")[1],
            ),
        ):
            binding = Mock()
            binding.bind.return_value = bound
            adapter = SupervisedBlueStacksAdapter(
                admission_token=token(),
                capture=lambda: sample(),
                executor=executor(),
                request_capability_binding=binding,
                connection_status=lambda: True,
                utc_clock=lambda: 11.0,
            )
            with self.assertRaises(AdapterError):
                adapter.execute(
                    SemanticActionIntent(
                        "named_action",
                        "flow",
                        "home",
                        "successor",
                        flow_id="flow",
                    )
                )

    def test_supervised_adapter_reports_connection_probe(self) -> None:
        binding = Mock()
        binding.bind.return_value = core_authority()
        adapter = SupervisedBlueStacksAdapter(
            admission_token=token(),
            capture=lambda: sample(),
            executor=executor(),
            request_capability_binding=binding,
            connection_status=lambda: False,
            utc_clock=lambda: 11.0,
        )
        self.assertFalse(adapter.status().connected)


if __name__ == "__main__":
    unittest.main()

