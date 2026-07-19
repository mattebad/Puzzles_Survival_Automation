"""Offline tests for the runtime input capability firewall."""

from __future__ import annotations

import copy
import dataclasses
import json
import pickle
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from safe_action_core import (
    CAPABILITY_ALREADY_CONSUMED,
    CAPABILITY_AUTHORIZED,
    CAPABILITY_COORDINATE_MISMATCH,
    CAPABILITY_DRY_RUN_ZERO_TRANSPORT,
    CAPABILITY_FORGERY,
    CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED,
    ActionClass,
    ActionStatus,
    CapabilityAuditRecord,
    CapabilityAuthorityBinding,
    CentralPolicy,
    InputCapability,
    Observation,
    PolicyDecision,
    PolicyRequest,
    SafeActionExecutor,
    SafetyStore,
    TransportResult,
)
from safe_action_core.models import (
    CAPABILITY_ACTION_KEY_MISMATCH,
    CAPABILITY_ACTION_CLASS_MISMATCH,
    CAPABILITY_ACTION_MISMATCH,
    CAPABILITY_CAPTURE_MISMATCH,
    CAPABILITY_CANDIDATE_CLAIMS_AUTHORITY,
    CAPABILITY_DIGEST_ONLY_REJECTED,
    CAPABILITY_DISPATCH_ALLOWED,
    CAPABILITY_GEOMETRY_MISMATCH,
    CAPABILITY_PROFILE_MISMATCH,
    CAPABILITY_PRE_DISPATCH_PHASE_REQUIRED,
    CAPABILITY_RETIRED_NO_DISPATCH,
    CAPABILITY_SCHEMA_INVALID,
    CAPABILITY_SEMANTIC_ACTION_MISMATCH,
    CAPABILITY_SESSION_MISMATCH,
    CAPABILITY_STALE_OBSERVATION,
    CAPABILITY_TARGET_MISMATCH,
    CAPABILITY_TASK_MISMATCH,
    CAPABILITY_TIMING_INVALID,
    CAPABILITY_UNKNOWN_CLASS_DENIED,
    CapabilityConsumeResult,
    CapabilityIssueResult,
    _CAPABILITY_MINT_SEAL,
    snapshot,
)


PROFILE = "pns-blissos-poc-virgl-800x1280-v1"
SESSION = "runtime-session-capability-1"
NAV_ROI = (250, 1130, 410, 1280)


class Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def nav_observation(**changes) -> Observation:
    base = Observation(
        frame_sha256="a" * 64,
        capture_completed_monotonic=999.5,
        runtime_profile_id=PROFILE,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="HOME_BASE",
        overlay_state="none_observed",
        target_identity="home-quest-entry",
        target_roi=NAV_ROI,
        recognized=True,
        consequence="navigate_zero_cost",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition="QUEST",
        evidence_refs=("synthetic:capability-nav",),
    )
    return replace(base, **changes)


def claim_observation(**changes) -> Observation:
    base = Observation(
        frame_sha256="c" * 64,
        capture_completed_monotonic=999.5,
        runtime_profile_id=PROFILE,
        width=800,
        height=1280,
        valid_png=True,
        corrupt=False,
        black=False,
        source_state="DAILY_QUEST",
        overlay_state="none_observed",
        target_identity="synthetic-test-only-claim-control",
        target_roi=(550, 500, 730, 580),
        recognized=True,
        control_class="CLAIM",
        consequence="claim_zero_cost_reward",
        cost_type="none",
        cost_amount=0,
        quantity=1,
        expected_postcondition="row_claimed_or_points_increased",
        evidence_refs=("synthetic:capability-claim",),
    )
    return replace(base, **changes)


def nav_request(obs: Observation | None = None, **changes) -> PolicyRequest:
    base = PolicyRequest(
        action_id="nav-capability-1",
        action_key="nav:capability:home-quest",
        task_id="MVP-QUEST-TO-CLAIM",
        task_mode="supervised_validation",
        semantic_action="HOME_TO_QUEST",
        expected_runtime_profile_id=PROFILE,
        observation=obs or nav_observation(),
        monotonic_now=1000.0,
        observation_max_age_seconds=5.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="executor-1",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        action_class=ActionClass.NAVIGATION_ONLY,
        runtime_session_id=SESSION,
    )
    return replace(base, **changes)


def claim_request(obs: Observation | None = None, **changes) -> PolicyRequest:
    base = PolicyRequest(
        action_id="claim-capability-1",
        action_key="day-1:claim:capability",
        task_id="MVP-QUEST-TO-CLAIM",
        task_mode="supervised_validation",
        semantic_action="CLAIM_DAILY_QUEST",
        expected_runtime_profile_id=PROFILE,
        observation=obs or claim_observation(),
        monotonic_now=1000.0,
        observation_max_age_seconds=5.0,
        dispatch_max_age_seconds=2.0,
        lease_owner="executor-1",
        lease_valid=True,
        unresolved_action=False,
        duplicate_action_key=False,
        game_day_id="day-1",
        action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
        runtime_session_id=SESSION,
    )
    return replace(base, **changes)


def dispatch_request(obs: Observation | None = None, **changes) -> PolicyRequest:
    return nav_request(obs, policy_phase="pre_dispatch", **changes)


class CapabilityFirewallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = SafetyStore(Path(self.temp.name) / "safety.sqlite3")
        self.clock = Clock()
        self.store.acquire_lease("executor-1", self.clock(), 100.0)
        self.policy = CentralPolicy()
        self.transport_calls = 0

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def transport(self, _intent) -> TransportResult:
        self.transport_calls += 1
        return TransportResult(True, "MOCK_DISPATCHED")

    def executor(self, pre: Observation, posts=None) -> SafeActionExecutor:
        post = posts
        if post is None:
            post = [
                nav_observation(
                    frame_sha256="f" * 64,
                    capture_completed_monotonic=1000.2,
                    source_state="QUEST",
                    target_identity=None,
                    target_roi=None,
                )
            ]
        return SafeActionExecutor(
            self.store,
            self.policy,
            "executor-1",
            self.clock,
            self.transport,
            lambda: pre,
            lambda: post,
            lambda _action, obs: obs.source_state == "QUEST",
        )

    def test_valid_navigation_one_shot_mocked_dispatch(self) -> None:
        initial = nav_observation()
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        self.assertTrue(issued.authorized)
        assert issued.capability is not None
        result = self.executor(immediate).execute(nav_request(initial), issued.capability)
        self.assertEqual(result.status, ActionStatus.CONFIRMED)
        self.assertEqual(result.transport_calls, 1)
        self.assertEqual(self.transport_calls, 1)
        self.assertTrue(issued.capability.consumed)

    def test_navigation_capability_cannot_dispatch_consequential(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        claim_pre = claim_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        result = SafeActionExecutor(
            self.store,
            self.policy,
            "executor-1",
            self.clock,
            self.transport,
            lambda: claim_pre,
            lambda: [claim_pre],
            lambda *_: True,
        ).execute(
            claim_request(
                claim_observation(),
                action_id="nav-capability-1",
                action_key="nav:capability:home-quest",
            ),
            issued.capability,
        )
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertIn(
            result.reason,
            {
                CAPABILITY_ACTION_CLASS_MISMATCH,
                CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED,
                CAPABILITY_TARGET_MISMATCH,
                CAPABILITY_SEMANTIC_ACTION_MISMATCH,
            },
        )
        self.assertEqual(self.transport_calls, 0)
        self.assertTrue(issued.capability.consumed)

    def test_unknown_class_denied(self) -> None:
        req = nav_request()
        object.__setattr__(req, "action_class", "not-an-enum")  # type: ignore[misc]
        issued = self.policy.issue_capability(req)
        self.assertFalse(issued.authorized)
        self.assertEqual(issued.reason_code, CAPABILITY_UNKNOWN_CLASS_DENIED)

    def test_scope_session_task_action_target_capture_digest_coordinate_mismatches(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        cases = [
            (nav_request(immediate, runtime_session_id="other-session"), CAPABILITY_SESSION_MISMATCH),
            (nav_request(immediate, task_id="OTHER-TASK"), CAPABILITY_TASK_MISMATCH),
            (nav_request(immediate, action_id="other-action"), CAPABILITY_ACTION_MISMATCH),
            (nav_request(immediate, action_key="other:key"), CAPABILITY_ACTION_KEY_MISMATCH),
            (
                nav_request(immediate, semantic_action="HOME_TO_OTHER"),
                CAPABILITY_SEMANTIC_ACTION_MISMATCH,
            ),
            (
                nav_request(immediate, action_class=ActionClass.ZERO_COST_CONSEQUENTIAL),
                CAPABILITY_ACTION_CLASS_MISMATCH,
            ),
            (
                nav_request(replace(immediate, target_identity="other-target")),
                CAPABILITY_TARGET_MISMATCH,
            ),
            (
                nav_request(replace(immediate, target_roi=(1, 2, 3, 4))),
                CAPABILITY_COORDINATE_MISMATCH,
            ),
            (
                nav_request(replace(immediate, runtime_profile_id="other-profile")),
                CAPABILITY_PROFILE_MISMATCH,
            ),
            (
                nav_request(replace(immediate, width=801)),
                CAPABILITY_GEOMETRY_MISMATCH,
            ),
            (
                nav_request(
                    replace(
                        immediate,
                        frame_sha256="b" * 64,
                        capture_completed_monotonic=999.7,
                    )
                ),
                CAPABILITY_DIGEST_ONLY_REJECTED,
            ),
            (
                nav_request(
                    replace(
                        immediate,
                        frame_sha256="d" * 64,
                        capture_completed_monotonic=999.8,
                    )
                ),
                CAPABILITY_CAPTURE_MISMATCH,
            ),
        ]
        for req, expected in cases:
            with self.subTest(expected=expected):
                fresh = self.policy.issue_capability(nav_request(immediate))
                assert fresh.capability is not None
                evaluated = self.policy.evaluate_capability(fresh.capability, req)
                self.assertEqual(evaluated.reason_code, expected)
                self.assertFalse(evaluated.allow_dispatch)

    def test_moved_target_final_revalidation(self) -> None:
        initial = nav_observation()
        bound = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        moved = replace(bound, target_roi=(260, 1130, 420, 1280))
        issued = self.policy.issue_capability(nav_request(bound))
        assert issued.capability is not None
        result = self.executor(moved).execute(nav_request(initial), issued.capability)
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertEqual(result.reason, CAPABILITY_COORDINATE_MISMATCH)
        self.assertEqual(self.transport_calls, 0)

    def test_stale_observation_denied(self) -> None:
        stale = nav_observation(capture_completed_monotonic=990.0)
        issued = self.policy.issue_capability(nav_request(stale, monotonic_now=1000.0))
        self.assertFalse(issued.authorized)
        self.assertEqual(issued.reason_code, "STALE_FRAME")
        # Fresh issue then stale compare at evaluate time.
        fresh = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(fresh))
        assert issued.capability is not None
        stale_req = nav_request(fresh, monotonic_now=1005.0, policy_phase="pre_dispatch")
        evaluated = self.policy.evaluate_capability(issued.capability, stale_req)
        self.assertEqual(evaluated.reason_code, CAPABILITY_STALE_OBSERVATION)

    def test_final_consume_rechecks_every_policy_guard(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        cases = (
            (dispatch_request(immediate, lease_valid=False, lease_owner=None), "LEASE_REQUIRED"),
            (dispatch_request(immediate, unresolved_action=True), "UNRESOLVED_ACTION"),
            (
                dispatch_request(replace(immediate, overlay_state="unknown")),
                "UNKNOWN_OVERLAY",
            ),
            (
                dispatch_request(replace(immediate, cost_type="food", cost_amount=1)),
                "NAVIGATION_COST_DENIED",
            ),
            (
                dispatch_request(replace(immediate, consequence="unknown")),
                "NAVIGATION_CONTRACT_INVALID",
            ),
            (
                dispatch_request(replace(immediate, package_foreground=False)),
                "NAVIGATION_HARD_STOP",
            ),
            (
                dispatch_request(replace(immediate, hard_stop_detected=True)),
                "NAVIGATION_HARD_STOP",
            ),
            (
                dispatch_request(replace(immediate, ambiguous=True)),
                "AMBIGUOUS_TARGET",
            ),
            (
                dispatch_request(immediate, task_id="OTHER-TASK"),
                "TASK_NOT_ENABLED",
            ),
            (
                dispatch_request(immediate, task_mode="disabled"),
                "TASK_MODE_DENIED",
            ),
        )
        for final_request, expected in cases:
            with self.subTest(expected=expected):
                issued = self.policy.issue_capability(nav_request(immediate))
                assert issued.capability is not None
                consumed = self.policy.consume_capability(issued.capability, final_request)
                self.assertTrue(consumed.consumed)
                self.assertFalse(consumed.allow_dispatch)
                self.assertEqual(consumed.reason_code, expected)
                self.assertEqual(consumed.audit.reason_code, expected)
                self.assertNotEqual(consumed.audit.event, CAPABILITY_DISPATCH_ALLOWED)

    def test_diagnostic_evaluation_never_grants_dispatch_and_rechecks_policy(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        evaluated = self.policy.evaluate_capability(
            issued.capability,
            nav_request(immediate, lease_valid=False, lease_owner=None),
        )
        self.assertTrue(evaluated.binding_matched)
        self.assertFalse(evaluated.allow_dispatch)
        self.assertEqual(evaluated.reason_code, "LEASE_REQUIRED")
        self.assertFalse(issued.capability.consumed)

    def test_proposal_phase_consume_is_terminally_denied(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        consumed = self.policy.consume_capability(issued.capability, nav_request(immediate))
        self.assertTrue(consumed.consumed)
        self.assertFalse(consumed.allow_dispatch)
        self.assertEqual(consumed.reason_code, CAPABILITY_PRE_DISPATCH_PHASE_REQUIRED)
        self.assertEqual(consumed.audit.event, "CAPABILITY_DISPATCH_REJECTED")

    def test_malformed_policy_timing_fails_closed_in_policy_and_consume(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        malformed = (
            {"monotonic_now": True},
            {"monotonic_now": float("nan")},
            {"monotonic_now": float("inf")},
            {"monotonic_now": -1.0},
            {"observation_max_age_seconds": True},
            {"observation_max_age_seconds": float("nan")},
            {"observation_max_age_seconds": float("inf")},
            {"observation_max_age_seconds": -1.0},
            {"dispatch_max_age_seconds": True},
            {"dispatch_max_age_seconds": float("nan")},
            {"dispatch_max_age_seconds": float("inf")},
            {"dispatch_max_age_seconds": -1.0},
        )
        for changes in malformed:
            with self.subTest(changes=changes):
                final_request = dispatch_request(immediate, **changes)
                decision = self.policy.evaluate(final_request)
                self.assertEqual(decision.reason_code, CAPABILITY_TIMING_INVALID)
                issued = self.policy.issue_capability(nav_request(immediate))
                assert issued.capability is not None
                consumed = self.policy.consume_capability(issued.capability, final_request)
                self.assertTrue(consumed.consumed)
                self.assertFalse(consumed.allow_dispatch)
                self.assertEqual(consumed.reason_code, CAPABILITY_TIMING_INVALID)

    def test_malformed_public_shapes_fail_closed_and_consume_terminal_attempt(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        missing_attribute = replace(immediate)
        object.__delattr__(missing_attribute, "frame_sha256")
        malformed_requests = (
            None,
            SimpleNamespace(policy_phase="pre_dispatch"),
            dispatch_request(replace(immediate, frame_sha256=123)),
            dispatch_request(replace(immediate, target_roi=[1, 2, 3, 4])),
            dispatch_request(replace(immediate, target_roi=(1, 2, "3", 4))),
            dispatch_request(replace(immediate, critical_roi_hashes=["bad"])),
            dispatch_request(replace(immediate, critical_roi_hashes=(("name", 123),))),
            dispatch_request(replace(immediate, forbidden_regions=["bad"])),
            dispatch_request(
                replace(immediate, forbidden_regions=(("dialog", [1, 2, 3, 4]),)),
                semantic_action="SAFE_PROMOTIONAL_BACK",
            ),
            replace(dispatch_request(immediate), observation=SimpleNamespace(frame_sha256="b" * 64)),
            replace(dispatch_request(immediate), observation=missing_attribute),
        )
        for malformed in malformed_requests:
            with self.subTest(malformed_type=type(malformed).__name__):
                decision = self.policy.evaluate(malformed)  # type: ignore[arg-type]
                self.assertEqual(decision.reason_code, CAPABILITY_SCHEMA_INVALID)
                issue_denial = self.policy.issue_capability(malformed)  # type: ignore[arg-type]
                self.assertFalse(issue_denial.authorized)
                self.assertEqual(issue_denial.reason_code, CAPABILITY_SCHEMA_INVALID)

                issued = self.policy.issue_capability(nav_request(immediate))
                assert issued.capability is not None
                evaluated = self.policy.evaluate_capability(
                    issued.capability, malformed  # type: ignore[arg-type]
                )
                self.assertFalse(evaluated.consumed)
                self.assertFalse(evaluated.allow_dispatch)
                self.assertEqual(evaluated.reason_code, CAPABILITY_SCHEMA_INVALID)

                consumed = self.policy.consume_capability(
                    issued.capability, malformed  # type: ignore[arg-type]
                )
                self.assertTrue(consumed.consumed)
                self.assertFalse(consumed.allow_dispatch)
                self.assertEqual(consumed.reason_code, CAPABILITY_SCHEMA_INVALID)
                self.assertEqual(consumed.audit.event, "CAPABILITY_DISPATCH_REJECTED")
                self.assertEqual(consumed.audit.decision, "deny")
                replay = self.policy.consume_capability(
                    issued.capability, dispatch_request(immediate)
                )
                self.assertEqual(replay.reason_code, CAPABILITY_ALREADY_CONSUMED)

    def test_executor_malformed_recapture_consumes_without_transport(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        missing_attribute = replace(immediate)
        object.__delattr__(missing_attribute, "target_roi")
        malformed_observations = (
            None,
            SimpleNamespace(frame_sha256="b" * 64),
            replace(immediate, frame_sha256=123),
            replace(immediate, target_roi=(1, 2, "3", 4)),
            replace(immediate, critical_roi_hashes=(("target", 123),)),
            replace(immediate, forbidden_regions=(("dialog", [1, 2, 3, 4]),)),
            missing_attribute,
        )
        for index, malformed in enumerate(malformed_observations):
            with self.subTest(index=index):
                action_id = f"malformed-recapture-{index}"
                action_key = f"nav:malformed-recapture:{index}"
                initial_request = nav_request(
                    nav_observation(),
                    action_id=action_id,
                    action_key=action_key,
                )
                final_request = nav_request(
                    immediate,
                    action_id=action_id,
                    action_key=action_key,
                )
                issued = self.policy.issue_capability(final_request)
                assert issued.capability is not None
                executor = SafeActionExecutor(
                    self.store,
                    self.policy,
                    "executor-1",
                    self.clock,
                    self.transport,
                    lambda value=malformed: value,  # type: ignore[return-value]
                    lambda: (),
                    lambda *_: False,
                )
                result = executor.execute(initial_request, issued.capability)
                self.assertEqual(result.status, ActionStatus.CANCELLED)
                self.assertEqual(result.reason, CAPABILITY_SCHEMA_INVALID)
                self.assertEqual(result.transport_calls, 0)
                self.assertTrue(issued.capability.consumed)
                replay = self.policy.consume_capability(
                    issued.capability, dispatch_request(immediate)
                )
                self.assertEqual(replay.reason_code, CAPABILITY_ALREADY_CONSUMED)
        self.assertEqual(self.transport_calls, 0)

    def test_forged_action_class_denied_by_policy_and_legacy_executor(self) -> None:
        request_value = nav_request(nav_observation())
        object.__setattr__(request_value, "action_class", "navigation_only")
        decision = self.policy.evaluate(request_value)
        self.assertEqual(decision.reason_code, CAPABILITY_UNKNOWN_CLASS_DENIED)
        result = self.executor(
            nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        ).execute(request_value)
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertEqual(result.reason, CAPABILITY_UNKNOWN_CLASS_DENIED)
        self.assertEqual(self.transport_calls, 0)

    def test_dry_run_zero_transport_allowed_and_rejected(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        result = self.executor(immediate).execute(
            nav_request(nav_observation()), issued.capability, dry_run=True
        )
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertEqual(result.reason, CAPABILITY_DRY_RUN_ZERO_TRANSPORT)
        self.assertEqual(self.transport_calls, 0)
        self.assertTrue(issued.capability.consumed)
        # Rejected dry-run path also issues zero transport.
        issued2 = self.policy.issue_capability(nav_request(immediate))
        assert issued2.capability is not None
        moved = replace(immediate, target_roi=(1, 2, 3, 4))
        result2 = self.executor(moved).execute(
            nav_request(nav_observation()), issued2.capability, dry_run=True
        )
        self.assertEqual(result2.status, ActionStatus.CANCELLED)
        self.assertEqual(self.transport_calls, 0)
        self.assertTrue(issued2.capability.consumed)

    def test_only_executor_dry_run_audit_proves_zero_transport(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        evaluated = self.policy.evaluate_capability(issued.capability, nav_request(immediate))
        self.assertIsNone(issued.audit.transport_occurred)
        self.assertIsNone(evaluated.audit.transport_occurred)
        result = self.executor(immediate).execute(
            nav_request(nav_observation()), issued.capability, dry_run=True
        )
        self.assertEqual(result.reason, CAPABILITY_DRY_RUN_ZERO_TRANSPORT)
        self.assertTrue(
            all(item.transport_occurred is None for item in self.policy.capability_audits)
        )
        rows = self.store.audit_events("nav-capability-1")
        dry_row = next(row for row in rows if row["event_type"] == "capability_executor_dry_run")
        payload = json.loads(dry_row["payload_json"])
        self.assertEqual(payload["transport_calls"], 0)
        self.assertIs(payload["transport_occurred"], False)
        self.assertTrue(payload["policy_allow_is_not_non_dispatch_proof"])

    def test_reuse_after_terminal_fails_closed(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        first = self.executor(immediate).execute(nav_request(nav_observation()), issued.capability)
        self.assertEqual(first.status, ActionStatus.CONFIRMED)
        second = self.executor(immediate).execute(nav_request(nav_observation()), issued.capability)
        self.assertEqual(second.status, ActionStatus.CANCELLED)
        self.assertEqual(second.reason, CAPABILITY_ALREADY_CONSUMED)
        self.assertEqual(self.transport_calls, 1)

    def test_process_global_block_consumes_supplied_capability_without_transport(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        executor = self.executor(immediate)
        executor._process_global_block = "prior_ambiguous_transport"
        result = executor.execute(nav_request(immediate), issued.capability)
        self.assertEqual(result.status, ActionStatus.CANCELLED)
        self.assertTrue(issued.capability.consumed)
        self.assertEqual(self.transport_calls, 0)
        retirement = self.policy.capability_audits[-1]
        self.assertEqual(retirement.event, "CAPABILITY_CONSUMED")
        self.assertEqual(retirement.reason_code, CAPABILITY_RETIRED_NO_DISPATCH)
        self.assertEqual(retirement.decision, "deny")
        self.assertFalse(retirement.policy_authorized)
        replay = self.policy.consume_capability(issued.capability, dispatch_request(immediate))
        self.assertEqual(replay.reason_code, CAPABILITY_ALREADY_CONSUMED)

    def test_copy_deepcopy_pickle_json_forbidden(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        with self.assertRaises(TypeError):
            copy.copy(issued.capability)
        with self.assertRaises(TypeError):
            copy.deepcopy(issued.capability)
        with self.assertRaises(TypeError):
            pickle.dumps(issued.capability)
        with self.assertRaises(TypeError):
            issued.capability.to_json()
        with self.assertRaises(TypeError):
            issued.capability.as_dict()
        with self.assertRaises(TypeError):
            json.dumps(issued.capability)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            snapshot(issued.capability)
        with self.assertRaises(TypeError):
            snapshot({"nested": issued.capability})

        @dataclasses.dataclass
        class Wrapper:
            capability: InputCapability

        with self.assertRaises(TypeError):
            dataclasses.asdict(Wrapper(issued.capability))
        with self.assertRaises(TypeError):
            dataclasses.asdict(issued)
        with self.assertRaises(TypeError):
            iter(issued.capability)
        representation = repr(issued.capability)
        self.assertNotIn("secret", representation.casefold())
        self.assertNotIn("token", representation.casefold())
        self.assertFalse(any("secret" in name.casefold() or "token" in name.casefold()
                             for name in InputCapability.__slots__))
        values = [getattr(issued.capability, name) for name in InputCapability.__slots__
                  if name != "__weakref__"]
        self.assertFalse(any(isinstance(value, bytes) for value in values))

    def test_public_constructor_forgery_rejected(self) -> None:
        with self.assertRaises(TypeError):
            InputCapability()
        with self.assertRaises(TypeError):
            InputCapability._mint("not-binding", 1)  # type: ignore[call-arg,arg-type]
        foreign = CentralPolicy()
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = foreign.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        evaluated = self.policy.evaluate_capability(issued.capability, nav_request(immediate))
        self.assertEqual(evaluated.reason_code, CAPABILITY_FORGERY)

    def test_registry_rejects_direct_mint_and_object_new_exploits(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.binding is not None
        forged = InputCapability._mint(
            issued.binding,
            self.policy._issuer_handle,
            "cap:externally-minted",
            _CAPABILITY_MINT_SEAL,
        )
        self.assertEqual(
            self.policy.evaluate_capability(forged, nav_request(immediate)).reason_code,
            CAPABILITY_FORGERY,
        )
        blank = object.__new__(InputCapability)
        self.assertEqual(
            self.policy.evaluate_capability(blank, nav_request(immediate)).reason_code,
            CAPABILITY_FORGERY,
        )
        self.assertIn("cap:invalid", repr(blank))

    def test_registry_rejects_every_capability_state_mutation(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        mutations = (
            ("_binding", CapabilityAuthorityBinding(
                task_id="MVP-QUEST-TO-CLAIM",
                runtime_session_id=SESSION,
                action_class=ActionClass.NAVIGATION_ONLY,
                action_id="other",
                action_key="other:key",
                semantic_action="HOME_TO_QUEST",
                target_identity="home-quest-entry",
                capture_frame_sha256="b" * 64,
                capture_completed_monotonic=999.8,
                runtime_profile_id=PROFILE,
                width=800,
                height=1280,
                target_roi=NAV_ROI,
            )),
            ("_redacted_ref", "cap:mutated"),
            ("_issuer_handle", object()),
            ("_consumed", True),
            ("_mint_marker", object()),
            ("_lock", object()),
        )
        for field_name, value in mutations:
            with self.subTest(field_name=field_name):
                issued = self.policy.issue_capability(nav_request(immediate))
                assert issued.capability is not None
                object.__setattr__(issued.capability, field_name, value)
                result = self.policy.evaluate_capability(issued.capability, nav_request(immediate))
                self.assertEqual(result.reason_code, CAPABILITY_FORGERY)

    def test_policy_lifecycle_and_simulated_id_reuse_cannot_transfer_authority(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        replacement_policy = CentralPolicy()
        replacement_policy._issuer_handle = self.policy._issuer_handle
        self.assertEqual(
            replacement_policy.evaluate_capability(issued.capability, nav_request(immediate)).reason_code,
            CAPABILITY_FORGERY,
        )

    def test_concurrent_double_consumption_allows_at_most_one(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def worker() -> None:
            barrier.wait()
            result = self.policy.consume_capability(issued.capability, dispatch_request(immediate))
            outcomes.append(result.reason_code)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(outcomes.count(CAPABILITY_DISPATCH_ALLOWED), 1)
        self.assertEqual(outcomes.count(CAPABILITY_ALREADY_CONSUMED), 1)
        self.assertTrue(issued.capability.consumed)

    def test_audit_redaction_immutability_and_reason_codes(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        self.assertEqual(issued.reason_code, CAPABILITY_AUTHORIZED)
        self.assertNotIn("secret", repr(issued.capability).lower())
        self.assertIn("cap:", issued.capability.redacted_ref)
        payload = issued.audit.as_dict()
        encoded = json.dumps(payload, sort_keys=True)
        self.assertNotIn("secret", encoded.casefold())
        self.assertNotIn("token", encoded.casefold())
        self.assertTrue(payload["policy_allow_is_not_non_dispatch_proof"])
        self.assertIsNone(payload["transport_occurred"])
        self.assertIsInstance(issued.audit.details, tuple)
        assert issued.binding is not None
        binding_audit = issued.binding.as_audit_dict()
        self.assertIsInstance(binding_audit["target_roi"], tuple)
        with self.assertRaises(TypeError):
            binding_audit["mutated"] = True  # type: ignore[index]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            issued.audit.reason_code = "TAMPERED"  # type: ignore[misc]
        object.__setattr__(issued.audit, "binding_fingerprint", "not-a-digest")
        with self.assertRaises(ValueError):
            issued.audit.as_dict()

    def test_audit_rejects_nested_and_secret_material_and_is_thread_safe(self) -> None:
        common = dict(
            event="CAPABILITY_ISSUED",
            reason_code=CAPABILITY_AUTHORIZED,
            decision="authorize",
            binding_fingerprint="a" * 64,
            capability_ref="cap:test",
            transport_calls=0,
            dry_run=False,
            policy_authorized=True,
            transport_occurred=None,
        )
        with self.assertRaises(ValueError):
            CapabilityAuditRecord(**common, details=(("policy_reason_code", ["nested"]),))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            CapabilityAuditRecord(**common, details=(("policy_reason_code", "secret-material"),))
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None
        before = len(self.policy.capability_audits)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda _: self.policy.evaluate_capability(
                        issued.capability, nav_request(immediate)
                    ),
                    range(24),
                )
            )
        self.assertTrue(all(item.reason_code == CAPABILITY_AUTHORIZED for item in results))
        self.assertEqual(len(self.policy.capability_audits), before + 24)

    def test_existing_consequential_path_unchanged_without_capability(self) -> None:
        initial = claim_observation()
        pre = claim_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        post = claim_observation(
            frame_sha256="e" * 64,
            capture_completed_monotonic=1000.2,
            source_state="DAILY_QUEST_POST",
            target_identity=None,
            target_roi=None,
            control_class=None,
        )
        executor = SafeActionExecutor(
            self.store,
            self.policy,
            "executor-1",
            self.clock,
            self.transport,
            lambda: pre,
            lambda: [post],
            lambda _action, obs: obs.source_state == "DAILY_QUEST_POST",
        )
        result = executor.execute(claim_request(initial))
        self.assertEqual(result.status, ActionStatus.CONFIRMED)
        self.assertEqual(self.transport_calls, 1)

    def test_single_executor_invariant(self) -> None:
        from safe_action_core import ActionTransaction

        self.assertIs(ActionTransaction, SafeActionExecutor)
        self.assertIs(self.policy.__class__, CentralPolicy)

    def test_confirmed_not_dispatched_remains_fail_closed(self) -> None:
        from tests.test_navigation_session import (
            begin_continuation,
            home_bundle,
            identity,
            prepared_uncertain_session,
            save_reload,
            scope,
        )
        from tasks.navigation_session import (
            NavigationSessionError,
            UncertainPreparedResolution,
            reconcile_uncertain_pan,
        )

        session, frame, _action_key, _fingerprint = prepared_uncertain_session()
        loaded = save_reload(session)
        fresh = identity(session=frame.runtime_session_id, ordinal=2, transport="3", semantic="4", monotonic=1001.0)
        begin_continuation(
            loaded, authorization=scope(), fresh_identity=fresh, perception_factory=lambda: home_bundle(fresh)
        )
        with self.assertRaises(NavigationSessionError) as ctx:
            reconcile_uncertain_pan(
                loaded,
                post_frame=fresh,
                resolution=UncertainPreparedResolution.CONFIRMED_NOT_DISPATCHED,
                reason="capability-firewall-regression",
                measured=(0.0, 0.0),
                progress_px=0.0,
            )
        self.assertEqual(ctx.exception.reason_code, "NON_DISPATCH_AUTHORITY_UNAVAILABLE")
        allowed = self.policy.evaluate(nav_request())
        self.assertEqual(allowed.decision, PolicyDecision.AUTHORIZE)
        self.assertNotEqual(allowed.reason_code, "CONFIRMED_NOT_DISPATCHED")

    def test_safe_exit_candidate_non_authorizing_only(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        honest = SimpleNamespace(authorize_dispatch=False, capability_grant=None, policy_grant=None)
        issued = self.policy.issue_capability(
            nav_request(immediate), non_authorizing_candidate=honest
        )
        self.assertTrue(issued.authorized)
        forged = SimpleNamespace(authorize_dispatch=True, capability_grant="token", policy_grant=None)
        denied = self.policy.issue_capability(
            nav_request(immediate), non_authorizing_candidate=forged
        )
        self.assertFalse(denied.authorized)
        self.assertEqual(denied.reason_code, CAPABILITY_CANDIDATE_CLAIMS_AUTHORITY)
        self.assertIsNone(denied.capability)

    def test_binding_schema_rejects_bool_and_mutable_collections(self) -> None:
        with self.assertRaises(ValueError):
            CapabilityAuthorityBinding(
                task_id="MVP-QUEST-TO-CLAIM",
                runtime_session_id=SESSION,
                action_class=ActionClass.NAVIGATION_ONLY,
                action_id="nav-1",
                action_key="nav:key",
                semantic_action="HOME_TO_QUEST",
                target_identity="home-quest-entry",
                capture_frame_sha256="a" * 64,
                capture_completed_monotonic=True,  # type: ignore[arg-type]
                runtime_profile_id=PROFILE,
                width=800,
                height=1280,
                target_roi=NAV_ROI,
            )
        with self.assertRaises(ValueError):
            CapabilityAuthorityBinding(
                task_id="MVP-QUEST-TO-CLAIM",
                runtime_session_id=SESSION,
                action_class=ActionClass.NAVIGATION_ONLY,
                action_id="nav-1",
                action_key="nav:key",
                semantic_action="HOME_TO_QUEST",
                target_identity="home-quest-entry",
                capture_frame_sha256="a" * 64,
                capture_completed_monotonic=999.5,
                runtime_profile_id=PROFILE,
                width=800,
                height=1280,
                target_roi=[250, 1130, 410, 1280],  # type: ignore[arg-type]
            )
        with self.assertRaises(ValueError):
            CapabilityAuditRecord(
                event="CAPABILITY_ISSUED",
                reason_code=CAPABILITY_AUTHORIZED,
                decision="authorize",
                binding_fingerprint="a" * 64,
                capability_ref="cap:test",
                transport_calls=True,  # type: ignore[arg-type]
                dry_run=False,
                policy_authorized=True,
                transport_occurred=None,
            )

    def test_binding_schema_rejects_malformed_ids_capture_and_geometry(self) -> None:
        cases = (
            nav_request(task_id=" bad"),
            nav_request(action_id="bad id"),
            nav_request(action_key="bad key"),
            nav_request(semantic_action=" BAD"),
            nav_request(runtime_session_id="bad session"),
            nav_request(nav_observation(target_identity="bad target")),
            nav_request(nav_observation(capture_completed_monotonic=-1.0)),
            nav_request(nav_observation(capture_completed_monotonic=float("inf"))),
            nav_request(nav_observation(width=True)),  # type: ignore[arg-type]
            nav_request(nav_observation(height=0)),
            nav_request(nav_observation(target_roi=(700, 1200, 900, 1300))),
        )
        for request_value in cases:
            with self.subTest(request=request_value):
                issued = self.policy.issue_capability(request_value)
                self.assertFalse(issued.authorized)
                self.assertEqual(issued.reason_code, CAPABILITY_SCHEMA_INVALID)

    def test_public_result_constructors_enforce_exact_nested_state(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        issued = self.policy.issue_capability(nav_request(immediate))
        assert issued.capability is not None and issued.binding is not None
        with self.assertRaises(ValueError):
            CapabilityIssueResult(
                authorized=True,
                reason_code=CAPABILITY_AUTHORIZED,
                policy_result=issued.policy_result,
                capability=None,
                audit=issued.audit,
                binding=issued.binding,
            )
        with self.assertRaises(ValueError):
            CapabilityConsumeResult(
                consumed=False,
                binding_matched=True,
                reason_code=CAPABILITY_DISPATCH_ALLOWED,
                audit=issued.audit,
                allow_dispatch=True,
            )

    def test_train_upgrade_claim_markers_denied_for_navigation_capability(self) -> None:
        for semantic in (
            "TRAIN_FIGHTER",
            "upgrade_building",
            "Claim_Daily_Quest",
            "purchase_item",
            "Premium_Action",
        ):
            with self.subTest(semantic=semantic):
                req = nav_request(semantic_action=semantic)
                issued = self.policy.issue_capability(req)
                self.assertFalse(issued.authorized)
                self.assertEqual(issued.reason_code, CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED)

    def test_navigation_control_allowlist_is_closed_and_case_insensitive_for_denials(self) -> None:
        immediate = nav_observation(frame_sha256="b" * 64, capture_completed_monotonic=999.8)
        for control_class in (
            "claim",
            "ClAiM",
            "train",
            "Upgrade",
            "purchase",
            "PrEmIuM",
            "arbitrary_unknown_control",
            "",
        ):
            with self.subTest(control_class=control_class):
                issued = self.policy.issue_capability(
                    nav_request(replace(immediate, control_class=control_class))
                )
                self.assertFalse(issued.authorized)
                self.assertEqual(
                    issued.reason_code, CAPABILITY_NAVIGATION_CONSEQUENTIAL_DENIED
                )
        for control_class in (
            None,
            "GO",
            "SAFE_PROMOTIONAL_BACK",
            "POPUP_DISMISS_X",
            "POPUP_DISMISS_CONFIRM",
            "RESET_CLOSE",
            "CLOSE",
        ):
            with self.subTest(allowed=control_class):
                issued = self.policy.issue_capability(
                    nav_request(replace(immediate, control_class=control_class))
                )
                self.assertTrue(issued.authorized)


if __name__ == "__main__":
    unittest.main()
