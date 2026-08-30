"""Focused tests for supervised and production runtime identity assurance."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tasks.runtime_identity import (
    FixedRuntimeBinding,
    ResourceResetWindow,
    RuntimeIdentityAssurance,
    RuntimeIdentityConfiguration,
    RuntimeIdentityObservation,
    RuntimePreflightObservation,
    RuntimePreflightStatus,
    derive_fixed_runtime_binding,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    evaluate_runtime_preflight,
    verify_runtime_identity,
)


PACKAGE = "com.global.ztmslg"
PROFILE = "pns-bluestacks-5-p64-800x1280-v1"
SERIAL = "emulator-5554"
LOGIN_SLOT_VERSION = "primary-login-slot-v1"


def _fixed_binding(
    *,
    serial: str = SERIAL,
    profile: str = PROFILE,
    package: str = PACKAGE,
    login_slot_version: str = LOGIN_SLOT_VERSION,
) -> FixedRuntimeBinding:
    return derive_fixed_runtime_binding(
        serial,
        profile,
        package,
        login_slot_version,
    )


def _configuration(*, reset_id: str | None = "reset-1") -> RuntimeIdentityConfiguration:
    return RuntimeIdentityConfiguration("bluestacks-dev-primary", "acct-1", "server-1", reset_id)


def _observation(
    *,
    account_id: str = "acct-1",
    server_id: str = "server-1",
    reset_id: str | None = "reset-1",
    operator_bound: bool = True,
    machine_observed: bool = False,
) -> RuntimeIdentityObservation:
    return RuntimeIdentityObservation(
        account_id,
        server_id,
        reset_id,
        ("identity-evidence.json",),
        operator_bound=operator_bound,
        machine_observed=machine_observed,
    )


def _preflight(**changes) -> RuntimePreflightObservation:
    values = {
        "expected_package": PACKAGE,
        "observed_package": PACKAGE,
        "expected_profile_id": PROFILE,
        "observed_profile_id": PROFILE,
        "native_width": 800,
        "native_height": 1280,
        "game_foregrounded": True,
        "manual_only_state": False,
        "blocking_unknown_modal": False,
        "captured_monotonic": 100.0,
        "evaluated_monotonic": 101.0,
        "evidence_refs": ("preflight-frame.png",),
    }
    values.update(changes)
    return RuntimePreflightObservation(**values)


def _resource_identity_case(
    evaluated: datetime = datetime(2026, 8, 19, 10, tzinfo=timezone.utc),
):
    binding = _fixed_binding()
    identity = derive_resource_runtime_identity(
        binding,
        evaluated,
        evidence_refs=("test:fixed-binding", "test:static-utc-reset"),
    )
    window = derive_static_utc_reset(evaluated)
    return binding, identity, window


class RuntimeIdentityTests(unittest.TestCase):
    def test_configuration_alone_is_never_observed_identity(self) -> None:
        result = verify_runtime_identity(
            _configuration(),
            None,
            required_assurance=RuntimeIdentityAssurance.CONFIGURATION_ONLY,
        )
        self.assertIsNone(result.identity)
        self.assertEqual(result.reason, "configuration_is_not_observed_identity")

    def test_supervised_navigation_requires_explicit_operator_binding(self) -> None:
        result = verify_runtime_identity(
            _configuration(),
            _observation(operator_bound=False),
            required_assurance=RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        )
        self.assertIsNone(result.identity)
        self.assertEqual(result.reason, "supervised_operator_binding_missing")

    def test_supervised_navigation_does_not_authorize_production(self) -> None:
        result = verify_runtime_identity(
            _configuration(),
            _observation(),
            required_assurance=RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        )
        self.assertIsNotNone(result.identity)
        assert result.identity is not None
        self.assertTrue(result.identity.permits_supervised_navigation)
        self.assertFalse(result.identity.permits_production_consequential)

    def test_account_server_and_reset_mismatches_fail_closed(self) -> None:
        for observation, reason, assurance in (
            (
                _observation(account_id="acct-2"),
                "account_identity_mismatch",
                RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
            ),
            (
                _observation(server_id="server-2"),
                "server_identity_mismatch",
                RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
            ),
            (
                _observation(reset_id="reset-2", operator_bound=False, machine_observed=True),
                "reset_identity_mismatch",
                RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
            ),
        ):
            with self.subTest(reason=reason):
                result = verify_runtime_identity(
                    _configuration(),
                    observation,
                    required_assurance=assurance,
                )
                self.assertIsNone(result.identity)
                self.assertEqual(result.reason, reason)

    def test_production_requires_machine_observed_complete_reset_identity(self) -> None:
        missing_machine = verify_runtime_identity(
            _configuration(),
            _observation(),
            required_assurance=RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
        )
        self.assertEqual(missing_machine.reason, "production_machine_observation_missing")
        missing_reset = verify_runtime_identity(
            _configuration(reset_id=None),
            _observation(
                reset_id=None,
                operator_bound=False,
                machine_observed=True,
            ),
            required_assurance=RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
        )
        self.assertEqual(missing_reset.reason, "production_reset_identity_missing")

    def test_production_observed_identity_authorizes_production_policy_boundary(self) -> None:
        result = verify_runtime_identity(
            _configuration(),
            _observation(operator_bound=False, machine_observed=True),
            required_assurance=RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
        )
        self.assertIsNotNone(result.identity)
        assert result.identity is not None
        self.assertTrue(result.identity.permits_supervised_navigation)
        self.assertTrue(result.identity.permits_production_consequential)

    def test_preflight_accepts_supervised_navigation_without_production_authority(self) -> None:
        identity = verify_runtime_identity(
            _configuration(),
            _observation(),
            required_assurance=RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        ).identity
        result = evaluate_runtime_preflight(_preflight(), identity)
        self.assertEqual(result.status, RuntimePreflightStatus.READY)
        self.assertTrue(result.navigation_authorized)
        self.assertFalse(result.production_consequential_authorized)

    def test_preflight_propagates_production_observed_assurance(self) -> None:
        identity = verify_runtime_identity(
            _configuration(),
            _observation(operator_bound=False, machine_observed=True),
            required_assurance=RuntimeIdentityAssurance.PRODUCTION_OBSERVED,
        ).identity
        result = evaluate_runtime_preflight(_preflight(), identity)
        self.assertEqual(result.status, RuntimePreflightStatus.READY)
        self.assertTrue(result.production_consequential_authorized)

    def test_manual_and_unknown_modal_states_fail_before_identity_use(self) -> None:
        manual = evaluate_runtime_preflight(_preflight(manual_only_state=True), None)
        self.assertEqual(manual.status, RuntimePreflightStatus.MANUAL_REQUIRED)
        unknown = evaluate_runtime_preflight(
            _preflight(blocking_unknown_modal=True),
            None,
        )
        self.assertEqual(unknown.status, RuntimePreflightStatus.BLOCKED)
        self.assertEqual(unknown.reason, "blocking_unknown_modal")

    def test_package_profile_dimensions_and_staleness_fail_closed(self) -> None:
        identity = verify_runtime_identity(
            _configuration(),
            _observation(),
            required_assurance=RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
        ).identity
        cases = (
            (
                _preflight(observed_package="other.package"),
                "unexpected_foreground_package",
            ),
            (
                _preflight(observed_profile_id="wrong-profile"),
                "unexpected_native_profile",
            ),
            (
                _preflight(native_width=720),
                "unexpected_native_profile",
            ),
            (
                _preflight(evaluated_monotonic=104.1),
                "stale_preflight_observation",
            ),
            (
                _preflight(evidence_refs=()),
                "preflight_evidence_missing",
            ),
        )
        for observation, reason in cases:
            with self.subTest(reason=reason):
                result = evaluate_runtime_preflight(observation, identity)
                self.assertEqual(result.status, RuntimePreflightStatus.BLOCKED)
                self.assertEqual(result.reason, reason)

    def test_preflight_without_verified_identity_blocks(self) -> None:
        result = evaluate_runtime_preflight(_preflight(), None)
        self.assertEqual(result.status, RuntimePreflightStatus.BLOCKED)
        self.assertEqual(result.reason, "verified_identity_unavailable")

    def test_static_reset_selects_previous_current_and_next_utc_windows(self) -> None:
        cases = (
            (
                datetime(2026, 8, 19, 23, 59, 59, 999999, tzinfo=timezone.utc),
                "2026-08-19T00:00:00Z",
                "2026-08-20T00:00:00Z",
            ),
            (
                datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc),
                "2026-08-20T00:00:00Z",
                "2026-08-21T00:00:00Z",
            ),
            (
                datetime(2026, 8, 20, 0, 0, 1, tzinfo=timezone.utc),
                "2026-08-20T00:00:00Z",
                "2026-08-21T00:00:00Z",
            ),
        )
        for evaluated, start, deadline in cases:
            with self.subTest(evaluated=evaluated):
                window = derive_static_utc_reset(evaluated)
                self.assertIsInstance(window, ResourceResetWindow)
                self.assertEqual(window.reset_start_text, start)
                self.assertEqual(window.reset_deadline_text, deadline)
                self.assertEqual(window.reset_identity_id, f"reset-deadline:{deadline}")

    def test_static_reset_rejects_naive_wall_clock(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            derive_static_utc_reset(datetime(2026, 8, 20, 0, 0, 1))

    def test_resource_identity_uses_static_assurance_and_clips_freshness(self) -> None:
        binding, identity, window = _resource_identity_case(
            datetime(2026, 8, 19, 23, 55, tzinfo=timezone.utc)
        )
        self.assertEqual(
            identity.assurance,
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_STATIC_UTC_RESET,
        )
        self.assertNotEqual(identity.assurance, RuntimeIdentityAssurance.PRODUCTION_OBSERVED)
        self.assertNotEqual(
            identity.assurance,
            RuntimeIdentityAssurance.FIXED_RUNTIME_BINDING_RESET_OBSERVED,
        )
        self.assertEqual(identity.reset_id, window.reset_identity_id)
        self.assertEqual(identity.reset_start_utc, window.reset_start_text)
        self.assertEqual(identity.reset_deadline_utc, window.reset_deadline_text)
        self.assertTrue(identity.permits_production_consequential)
        self.assertEqual(
            identity.expires_utc,
            "2026-08-20T00:00:00Z",
        )
        self.assertEqual(identity.runtime_binding_digest, binding.binding_digest)

    def test_static_identity_requires_fixed_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixed runtime binding"):
            derive_resource_runtime_identity(
                object(), datetime(2026, 8, 20, tzinfo=timezone.utc)
            )

    def test_static_identity_freshness_default_is_ten_minutes(self) -> None:
        _binding, identity, _window = _resource_identity_case(
            datetime(2026, 8, 19, 10, tzinfo=timezone.utc)
        )
        self.assertEqual(identity.expires_utc, "2026-08-19T10:10:00Z")

    def test_fixed_runtime_binding_is_stable_and_changes_for_each_binding_input(self) -> None:
        baseline = _fixed_binding()
        self.assertEqual(baseline, _fixed_binding())
        for changes in (
            {"serial": "emulator-5556"},
            {"profile": "pns-bluestacks-5-p64-720x1280-v2"},
            {"package": "com.example.other"},
            {"login_slot_version": "primary-login-slot-v2"},
        ):
            with self.subTest(changes=changes):
                changed = _fixed_binding(**changes)
                self.assertNotEqual(changed.binding_digest, baseline.binding_digest)
                self.assertNotEqual(changed.account_id, baseline.account_id)
                self.assertNotEqual(changed.server_id, baseline.server_id)


if __name__ == "__main__":
    unittest.main()
