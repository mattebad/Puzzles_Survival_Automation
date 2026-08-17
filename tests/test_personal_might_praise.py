from __future__ import annotations

from dataclasses import replace
import unittest

from tasks import daily_quest
from tasks.daily_quest import PersonalMightPraiseHandler, PraiseObservation


def observation(**changes) -> PraiseObservation:
    values = {
        "screen_state": "DAILY_QUEST",
        "objective_name": "Praise 1x in Personal Might rank",
        "current_progress": 0,
        "required_progress": 1,
    }
    values.update(changes)
    return PraiseObservation(**values)


class PersonalMightCompletionAttributionTests(unittest.TestCase):
    def test_catalog_alias_and_progress_are_attributed(self) -> None:
        self.assertTrue(
            PersonalMightPraiseHandler.matches_objective(
                "  personal   might praise "
            )
        )
        self.assertEqual(
            PersonalMightPraiseHandler.parse_progress(
                "Praise 1x in Personal Might rank 0/1"
            ),
            (0, 1),
        )
        self.assertEqual(PersonalMightPraiseHandler.remaining(observation()), 1)
        self.assertTrue(
            PersonalMightPraiseHandler.completion_check(
                replace(observation(), current_progress=1)
            )
        )

    def test_provider_exposes_no_action_or_claim_authority(self) -> None:
        for name in (
            "authorizeable",
            "transaction_spec",
            "perform_one_pulse",
            "postcondition_verified",
            "route_name",
            "consequence",
        ):
            self.assertFalse(hasattr(PersonalMightPraiseHandler, name))
        for name in (
            "DailyQuestClaimObservation",
            "claim_authorizeable",
            "claim_postcondition_verified",
            "PRAISE_NAVIGATION_BY_NAME",
            "RESET_POPUP_DISMISS_STEP",
            "PERSONAL_MIGHT_PRAISE_ROUTE",
            "PERSONAL_MIGHT_PRAISE_HANDLER",
            "QUEST_HANDLERS",
            "handler_for_objective",
        ):
            self.assertFalse(hasattr(daily_quest, name))

    def test_completion_contract_has_no_fixed_bliss_profile_import(self) -> None:
        source_names = set(daily_quest.__dict__)
        self.assertNotIn("MIGHT_PRAISE_ACTION", source_names)
        self.assertNotIn("HELP_ALL_ACTION", source_names)
        self.assertNotIn("PROFILE_ID", source_names)


if __name__ == "__main__":
    unittest.main()
