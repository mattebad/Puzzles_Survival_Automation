"""Personal Might Praise stays inside its exact free daily policy contract."""

from dataclasses import replace
import unittest

from safe_action_core import ActionClass, CentralPolicy, Observation, PolicyDecision, PolicyRequest
from tasks.personal_might_praise import (
    CONSEQUENCE,
    CONTROL_CLASS,
    FLOW_ID,
    POSTCONDITION,
    SEMANTIC_ACTION,
    SOURCE_STATE,
    TARGET_IDENTITY,
    personal_might_daily_key,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


PROFILE = ACTIVE_RUNTIME_PROFILE_ID
OTHER_TASK = "OTHER-SUPERVISED-ZERO-COST-TASK"
DAILY_SCOPE = dict(runtime_scope="local-bluestacks", account_id="account-1",
                   server_id="server-1", reset_id="game-day-2026-10-29")


def _observation(**changes):
    return replace(Observation(
        frame_sha256="a" * 64, capture_completed_monotonic=999.5,
        runtime_profile_id=PROFILE, width=800, height=1280,
        valid_png=True, corrupt=False, black=False,
        source_state=SOURCE_STATE, overlay_state="none_observed",
        target_identity=TARGET_IDENTITY, target_roi=(590, 350, 710, 430),
        recognized=True, control_class=CONTROL_CLASS, consequence=CONSEQUENCE,
        cost_type="none", cost_amount=0, quantity=1,
        expected_postcondition=POSTCONDITION, target_isolated=True,
        evidence_refs=("synthetic-policy-test-only",),
    ), **changes)


def _request(observation=None, **changes):
    return replace(PolicyRequest(
        action_id="personal-might-praise-1", action_key=personal_might_daily_key(**DAILY_SCOPE),
        task_id=FLOW_ID, task_mode="supervised_validation", semantic_action=SEMANTIC_ACTION,
        expected_runtime_profile_id=PROFILE, observation=observation or _observation(),
        monotonic_now=1000.0, observation_max_age_seconds=5.0, dispatch_max_age_seconds=2.0,
        lease_owner="personal-might-runner", lease_valid=True,
        unresolved_action=False, duplicate_action_key=False,
        game_day_id=DAILY_SCOPE["reset_id"], runtime_session_id="personal-might-runtime-session",
        action_class=ActionClass.ZERO_COST_CONSEQUENTIAL, free_only=True, maximum_cost=0,
    ), **changes)


def _ordinary_claim(**changes):
    return _request(_observation(
        source_state="DAILY_QUEST", target_identity="other-daily-quest-claim",
        control_class="CLAIM", consequence="claim_zero_cost_reward",
        expected_postcondition="DAILY_QUEST_RESULT",
    ), task_id=OTHER_TASK, semantic_action="CLAIM_DAILY_QUEST", free_only=False,
        maximum_cost=None, **changes)


def _ordinary_navigation(*, source=SOURCE_STATE, task=FLOW_ID):
    return _request(_observation(
        source_state=source, target_identity="ordinary-game-back", control_class="CLOSE",
        consequence="navigate_zero_cost", expected_postcondition="HOME_BASE",
    ), task_id=task, semantic_action="RETURN_HOME", action_class=ActionClass.NAVIGATION_ONLY,
        free_only=False, maximum_cost=None)


class PersonalMightPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = CentralPolicy({FLOW_ID, OTHER_TASK})

    def assert_not_authorized(self, request):
        issued = self.policy.issue_capability(request)
        self.assertFalse(issued.authorized)
        self.assertIsNone(issued.capability)
        self.assertNotEqual(issued.policy_result.decision, PolicyDecision.AUTHORIZE)
        return issued.policy_result

    def test_exact_current_free_praise_mints_existing_zero_cost_capability(self):
        request = _request()
        issued = self.policy.issue_capability(request)
        self.assertTrue(issued.authorized)
        self.assertIsNotNone(issued.capability)
        self.assertEqual(issued.policy_result.decision, PolicyDecision.AUTHORIZE)
        self.assertEqual(issued.policy_result.reason_code, "AUTHORIZED_PERSONAL_MIGHT_PRAISE")
        self.assertIs(request.action_class, ActionClass.ZERO_COST_CONSEQUENTIAL)

    def test_exact_action_fields_and_current_daily_context_are_required(self):
        candidates = (
            _request(task_id=OTHER_TASK),
            _request(semantic_action="PRAISE_OTHER_FREE"),
            _request(_observation(source_state="NOVA")),
            _request(_observation(target_identity="other-praise")),
            _request(_observation(control_class="CLAIM")),
            _request(_observation(consequence="claim_zero_cost_reward")),
            _request(_observation(expected_postcondition="OTHER_PRAISE_RESULT")),
            _request(_observation(cost_type="premium", cost_amount=1)),
            _request(_observation(cost_type="none", cost_amount=1)),
            _request(_observation(cost_type="AP", cost_amount=0)),
            _request(_observation(quantity=2)),
            _request(_observation(target_isolated=False)),
            _request(free_only=False),
            _request(maximum_cost=1),
            _request(maximum_cost=None),
            _request(game_day_id=None),
            _request(game_day_id=""),
            _request(game_day_id=" "),
        )
        for request in candidates:
            with self.subTest(request=request):
                self.assert_not_authorized(request)

    def test_generic_frame_target_lease_and_duplicate_fences_remain_closed(self):
        observations = (
            _observation(recognized=False),
            _observation(overlay_state="unknown"),
            _observation(target_roi=(600, 400, 590, 430)),
            _observation(target_roi=(780, 350, 820, 430)),
            _observation(target_roi=None),
            _observation(clipped=True),
            _observation(ambiguous=True),
            _observation(forbidden_region_intersects_target=True),
            _observation(valid_png=False),
            _observation(corrupt=True),
            _observation(black=True),
            _observation(runtime_profile_id="other-runtime-profile"),
            _observation(width=801),
            _observation(frame_sha256="invalid"),
            _observation(capture_completed_monotonic=990.0),
        )
        for observation in observations:
            with self.subTest(observation=observation):
                self.assert_not_authorized(_request(observation))
        for changes in ({"lease_valid": False}, {"lease_owner": None},
                        {"duplicate_action_key": True}, {"unresolved_action": True}):
            with self.subTest(changes=changes):
                self.assert_not_authorized(_request(**changes))

    def test_foreground_os_and_manual_hard_stops_lock_input_individually(self):
        for changes in ({"package_foreground": False}, {"os_surface": True}, {"hard_stop_detected": True}):
            with self.subTest(changes=changes):
                result = self.assert_not_authorized(_request(_observation(**changes)))
                self.assertEqual(result.decision, PolicyDecision.GLOBAL_INPUT_LOCK)

    def test_exact_action_or_target_cannot_borrow_another_route_or_action_class(self):
        ordinary = _ordinary_navigation(source="HOME_BASE", task=OTHER_TASK)
        for action_class in ActionClass:
            for reserved in ("semantic_action", "target_identity"):
                candidate = replace(ordinary, action_class=action_class)
                if reserved == "semantic_action":
                    candidate = replace(candidate, semantic_action=SEMANTIC_ACTION)
                else:
                    candidate = replace(candidate, observation=replace(candidate.observation,
                                                                        target_identity=TARGET_IDENTITY))
                with self.subTest(action_class=action_class, reserved=reserved):
                    self.assert_not_authorized(candidate)

    def test_zero_cost_task_and_rank_source_cannot_use_generic_r1_fallback(self):
        ordinary = _ordinary_claim()
        for candidate in (
            replace(ordinary, task_id=FLOW_ID),
            replace(ordinary, observation=replace(ordinary.observation, source_state=SOURCE_STATE)),
        ):
            with self.subTest(candidate=candidate):
                self.assert_not_authorized(candidate)

    def test_task_navigation_and_unrelated_zero_cost_r1_behavior_are_preserved(self):
        for source in ("HOME_BASE", SOURCE_STATE):
            with self.subTest(navigation_source=source):
                issued = self.policy.issue_capability(_ordinary_navigation(source=source))
                self.assertTrue(issued.authorized)
                self.assertEqual(issued.policy_result.reason_code, "AUTHORIZED_NAVIGATION_ONLY")
        unrelated = self.policy.issue_capability(_ordinary_claim())
        self.assertTrue(unrelated.authorized)
        self.assertEqual(unrelated.policy_result.reason_code, "AUTHORIZED_ZERO_COST_R1")

    def test_personal_might_remains_disabled_without_explicit_task_enablement(self):
        issued = CentralPolicy().issue_capability(_request())
        self.assertFalse(issued.authorized)
        self.assertIsNone(issued.capability)
        self.assertEqual(issued.policy_result.reason_code, "TASK_NOT_ENABLED")


class PersonalMightDailyKeyTests(unittest.TestCase):
    def test_key_is_stable_across_argument_order_and_changes_for_each_scope_dimension(self):
        key = personal_might_daily_key(**DAILY_SCOPE)
        self.assertIsInstance(key, str)
        self.assertTrue(key)
        self.assertEqual(key, personal_might_daily_key(**dict(reversed(tuple(DAILY_SCOPE.items())))))
        for name in DAILY_SCOPE:
            with self.subTest(dimension=name):
                changed = dict(DAILY_SCOPE, **{name: f"{DAILY_SCOPE[name]}-other"})
                self.assertNotEqual(key, personal_might_daily_key(**changed))

    def test_structured_scope_values_do_not_collide_at_delimiters(self):
        first = dict(DAILY_SCOPE, runtime_scope="a:b", account_id="c")
        second = dict(DAILY_SCOPE, runtime_scope="a", account_id="b:c")
        self.assertNotEqual(personal_might_daily_key(**first), personal_might_daily_key(**second))

    def test_missing_blank_whitespace_and_non_string_identities_are_rejected(self):
        for name in DAILY_SCOPE:
            missing = dict(DAILY_SCOPE)
            del missing[name]
            with self.subTest(missing=name), self.assertRaises(TypeError):
                personal_might_daily_key(**missing)
            for invalid in (None, "", " ", "\t", " leading", "trailing ", "inside space", 0, True):
                with self.subTest(dimension=name, invalid=invalid), self.assertRaises(ValueError):
                    personal_might_daily_key(**dict(DAILY_SCOPE, **{name: invalid}))

    def test_daily_key_does_not_accept_frame_time_or_task_overrides(self):
        for extra in ({"frame_sha256": "a" * 64}, {"captured_monotonic": 999.0}, {"task_id": OTHER_TASK}):
            with self.subTest(extra=extra), self.assertRaises(TypeError):
                personal_might_daily_key(**DAILY_SCOPE, **extra)


if __name__ == "__main__":
    unittest.main()
