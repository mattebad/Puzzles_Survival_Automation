from __future__ import annotations

from dataclasses import replace
import unittest

from safe_action_core.popup import PopupController, PopupObservation
from tasks import daily_quest
from tasks.contracts import (
    AnchorSpec,
    NavigationStep,
    PopupMode,
    PopupOutcome,
    TaskOutcome,
    TaskResult,
)
from tasks.daily_quest import (
    AllianceHelpHandler,
    AllianceHelpObservation,
    DailyQuestTask,
    RouteDispatcher,
    RouteObservation,
    RouteType,
)


class ContractTests(unittest.TestCase):
    def test_navigation_requires_source_and_successor(self) -> None:
        anchor = AnchorSpec("test", (0, 0, 10, 10), 0.9, template="test.png")
        step = NavigationStep(
            "route",
            "SOURCE",
            "ACTION",
            ("SUCCESSOR",),
            target_anchor=anchor,
        )
        self.assertEqual(step.target_anchor, anchor)
        with self.assertRaises(ValueError):
            NavigationStep("invalid", None, "BACK", ())

    def test_task_return_does_not_imply_done(self) -> None:
        task = DailyQuestTask("day-1:objective-complete")
        progress = task.apply(TaskResult.progress("observed progress", "DAILY_QUEST"))
        self.assertEqual(progress.outcome, TaskOutcome.PROGRESS)
        self.assertFalse(task.completed)
        done = task.apply(
            TaskResult.done(
                "completion attributed",
                "day-1:objective-complete",
                "DAILY_QUEST",
            )
        )
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertTrue(task.completed)

    def test_unverified_done_is_failed_safe(self) -> None:
        task = DailyQuestTask("day-1:objective-complete")
        result = task.apply(
            TaskResult(
                TaskOutcome.DONE,
                "returned from provider",
                verified=False,
                completion_key="day-1:objective-complete",
            )
        )
        self.assertEqual(result.outcome, TaskOutcome.FAILED_SAFE)
        self.assertFalse(task.completed)

    def test_alliance_help_is_completion_attribution_only(self) -> None:
        observation = AllianceHelpObservation(
            screen_state="DAILY_QUEST",
            objective_name="Help allies",
            current_progress=9,
            required_progress=10,
        )
        self.assertEqual(AllianceHelpHandler.remaining(observation), 1)
        self.assertTrue(
            AllianceHelpHandler.completion_check(
                replace(observation, current_progress=10)
            )
        )
        for name in (
            "authorizeable",
            "transaction_spec",
            "perform_one_pulse",
            "postcondition_verified",
            "selected_action_kind",
            "route_name",
            "consequence",
        ):
            self.assertFalse(hasattr(AllianceHelpHandler, name))
        for name in (
            "ALLIANCE_HELP_ROUTE",
            "ALLIANCE_HELP_HANDLER",
            "QUEST_HANDLERS",
            "handler_for_objective",
        ):
            self.assertFalse(hasattr(daily_quest, name))


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = RouteDispatcher()

    def test_supported_routes_are_distinct(self) -> None:
        self.assertEqual(
            self.dispatcher.classify(RouteObservation("DAILY_QUEST", True)),
            RouteType.DAILY_QUEST,
        )
        self.assertEqual(
            self.dispatcher.classify(RouteObservation("ALLIANCE", True)),
            RouteType.ALLIANCE,
        )
        self.assertEqual(
            self.dispatcher.classify(RouteObservation("WORLD", True)),
            RouteType.WORLD,
        )

    def test_unknown_and_hard_stop_routes_fail_closed(self) -> None:
        self.assertEqual(
            self.dispatcher.classify(RouteObservation(None, False)),
            RouteType.UNKNOWN_UNSAFE,
        )
        self.assertEqual(
            self.dispatcher.classify(
                RouteObservation("LOGIN", False, hard_stop=True)
            ),
            RouteType.ACCOUNT_OR_SESSION_HARD_STOP,
        )


class PopupTests(unittest.TestCase):
    def test_navigation_handles_only_known_benign_popup(self) -> None:
        controller = PopupController(PopupMode.NAVIGATION, max_rounds=1)
        self.assertEqual(
            controller.inspect(
                PopupObservation("vip-points-reset", benign=True)
            ),
            PopupOutcome.HANDLED,
        )
        self.assertEqual(
            controller.inspect(PopupObservation("info", benign=True)),
            PopupOutcome.UNKNOWN,
        )

    def test_action_transaction_blocks_unknown_or_cost_popup(self) -> None:
        controller = PopupController(
            PopupMode.ACTION_TRANSACTION,
            allowed_dialogs=("known-confirm",),
        )
        self.assertEqual(
            controller.inspect(PopupObservation("unknown", benign=True)),
            PopupOutcome.UNKNOWN,
        )
        self.assertEqual(
            controller.inspect(
                PopupObservation("purchase", purchase_or_cost=True)
            ),
            PopupOutcome.BLOCKING,
        )
        self.assertEqual(
            controller.inspect(PopupObservation("known-confirm")),
            PopupOutcome.HANDLED,
        )


if __name__ == "__main__":
    unittest.main()
