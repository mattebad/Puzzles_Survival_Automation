from __future__ import annotations

import unittest

from safe_action_core.popup import PopupController, PopupObservation
from tasks.contracts import AnchorSpec, NavigationStep, PopupMode, PopupOutcome, TaskOutcome, TaskResult
from tasks.daily_quest import (
    ALLIANCE_HELP_HANDLER,
    AllianceHelpHandler,
    AllianceHelpObservation,
    DailyQuestTask,
    RouteDispatcher,
    RouteObservation,
    RouteType,
    handler_for_objective,
)
from tasks.profile import HELP_ALL_ACTION, HOME_QUEST, QUEST_DAILY, PROFILE_ID


class ContractTests(unittest.TestCase):
    def test_profile_anchors_are_fixed_and_provenanced(self):
        self.assertEqual(PROFILE_ID, "pns-blissos-poc-virgl-800x1280-v1")
        self.assertEqual(HOME_QUEST.roi, (250, 1130, 410, 1280))
        self.assertEqual(QUEST_DAILY.roi, (300, 70, 500, 140))
        self.assertEqual(((QUEST_DAILY.roi[0] + QUEST_DAILY.roi[2]) // 2,
                          (QUEST_DAILY.roi[1] + QUEST_DAILY.roi[3]) // 2), (400, 105))
        self.assertTrue(HOME_QUEST.asset_provenance.endswith("home-base-settled.png"))
        self.assertEqual(QUEST_DAILY.required_confirmation_frames, 1)
        self.assertEqual(HELP_ALL_ACTION.roi, (556, 274, 727, 330))
        self.assertTrue(HELP_ALL_ACTION.asset_provenance.endswith("help-go-post-002.png"))

    def test_anchor_thresholds_are_anchor_specific(self):
        a = AnchorSpec("a", (0, 0, 10, 10), 0.81, template="a.png")
        b = AnchorSpec("b", (0, 0, 10, 10), 0.97, ocr_rule="Daily Quest")
        self.assertNotEqual(a.threshold, b.threshold)

    def test_navigation_requires_source_and_successor(self):
        step = NavigationStep("home-quest", "HOME_BASE", "HOME_TO_QUEST", ("QUEST",), target_anchor=HOME_QUEST)
        self.assertEqual(step.target_anchor.name, "home-quest-entry")
        with self.assertRaises(ValueError):
            NavigationStep("invalid", None, "BACK", ())

    def test_task_return_does_not_imply_done(self):
        task = DailyQuestTask("day-1:claim:objective")
        progress = task.apply(TaskResult.progress("navigation reached Quest", "QUEST"))
        self.assertEqual(progress.outcome, TaskOutcome.PROGRESS)
        self.assertFalse(task.completed)
        done = task.apply(TaskResult.done("claimed", "day-1:claim:objective", "DAILY_QUEST"))
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertTrue(task.completed)

    def test_unverified_done_is_failed_safe(self):
        task = DailyQuestTask("day-1:claim:objective")
        result = task.apply(TaskResult(TaskOutcome.DONE, "returned from handler", verified=False, completion_key="day-1:claim:objective"))
        self.assertEqual(result.outcome, TaskOutcome.FAILED_SAFE)
        self.assertFalse(task.completed)

    def test_alliance_help_registry_and_transaction_spec(self):
        self.assertIs(handler_for_objective(" Help   allies "), ALLIANCE_HELP_HANDLER)
        observation = AllianceHelpObservation(
            screen_state="ALLIANCE", objective_name="Help allies", current_progress=0,
            required_progress=10, target_identity=HELP_ALL_ACTION.name,
            target_roi=HELP_ALL_ACTION.roi, zero_cost_evidence=True,
            available_request_count=1, help_all_visible=True, request_controls_count=1,
        )
        self.assertEqual(AllianceHelpHandler.remaining(observation), 10)
        spec = AllianceHelpHandler.transaction_spec(observation)
        self.assertTrue(spec.free_only)
        self.assertEqual(spec.maximum_cost, 0)
        self.assertEqual(spec.action_kind, "ALLIANCE_HELP_ALL")

    def test_alliance_help_requires_exact_zero_cost_and_positive_postcondition(self):
        base = AllianceHelpObservation(
            screen_state="ALLIANCE", objective_name="Help allies", current_progress=0,
            required_progress=10, target_identity=HELP_ALL_ACTION.name,
            target_roi=HELP_ALL_ACTION.roi, zero_cost_evidence=True,
            available_request_count=1, help_all_visible=True, request_controls_count=1,
        )
        self.assertTrue(AllianceHelpHandler.authorizeable(base))
        self.assertFalse(AllianceHelpHandler.authorizeable(
            AllianceHelpObservation(**{**base.__dict__, "zero_cost_evidence": False})
        ))
        self.assertTrue(AllianceHelpHandler.postcondition_verified(
            base, AllianceHelpObservation(**{**base.__dict__, "current_progress": 1})
        ))
        self.assertFalse(AllianceHelpHandler.postcondition_verified(
            base, AllianceHelpObservation(**{**base.__dict__, "current_progress": 0})
        ))
        self.assertFalse(AllianceHelpHandler.postcondition_verified(
            base, AllianceHelpObservation(**{**base.__dict__, "current_progress": 11})
        ))
        self.assertTrue(AllianceHelpHandler.postcondition_verified(
            base, AllianceHelpObservation(**{**base.__dict__, "help_all_visible": False,
                                             "available_request_count": 0,
                                             "request_controls_count": 0, "empty_state": True})
        ))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = RouteDispatcher()

    def test_supported_routes_are_distinct(self):
        self.assertEqual(self.dispatcher.classify(RouteObservation("DAILY_QUEST", True)), RouteType.DAILY_QUEST)
        self.assertEqual(self.dispatcher.classify(RouteObservation("ALLIANCE", True)), RouteType.ALLIANCE)
        self.assertEqual(self.dispatcher.classify(RouteObservation("WORLD", True)), RouteType.WORLD)
        self.assertEqual(self.dispatcher.classify(RouteObservation("DIRECT_SCREEN", True)), RouteType.DIRECT_TASK_SCREEN)

    def test_home_route_variants(self):
        self.assertEqual(self.dispatcher.classify(RouteObservation("HOME_BASE", True, highlighted_building=True)), RouteType.HOME_WITH_HIGHLIGHTED_BUILDING)
        self.assertEqual(self.dispatcher.classify(RouteObservation("HOME_BASE", True, search_required=True)), RouteType.HOME_SEARCH_REQUIRED)

    def test_unknown_and_hard_stop_routes_fail_closed(self):
        self.assertEqual(self.dispatcher.classify(RouteObservation(None, False)), RouteType.UNKNOWN_UNSAFE)
        self.assertEqual(self.dispatcher.classify(RouteObservation("LOGIN", False, hard_stop=True)), RouteType.ACCOUNT_OR_SESSION_HARD_STOP)
        self.assertEqual(self.dispatcher.classify(RouteObservation(None, False, source_family="promotional", verified_back=True)), RouteType.UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK)


class PopupTests(unittest.TestCase):
    def test_navigation_handles_at_most_one_benign_popup_per_round(self):
        controller = PopupController(PopupMode.NAVIGATION, max_rounds=1)
        self.assertEqual(controller.inspect(PopupObservation("info", benign=True)), PopupOutcome.HANDLED)
        self.assertEqual(controller.inspect(PopupObservation("info", benign=True)), PopupOutcome.BLOCKING)

    def test_action_transaction_does_not_handle_generic_popup(self):
        controller = PopupController(PopupMode.ACTION_TRANSACTION, allowed_dialogs=("known-confirm",))
        self.assertEqual(controller.inspect(PopupObservation("unknown", benign=True)), PopupOutcome.UNKNOWN)
        self.assertEqual(controller.inspect(PopupObservation("purchase", purchase_or_cost=True)), PopupOutcome.BLOCKING)
        self.assertEqual(controller.inspect(PopupObservation("known-confirm")), PopupOutcome.HANDLED)

    def test_hard_stop_is_fatal(self):
        controller = PopupController(PopupMode.NAVIGATION)
        self.assertEqual(controller.inspect(PopupObservation("login", hard_stop=True)), PopupOutcome.FATAL)


if __name__ == "__main__":
    unittest.main()
