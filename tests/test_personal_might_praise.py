from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
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

    def test_matrix_retires_legacy_dispatch_and_keeps_completion_owner(self) -> None:
        matrix_path = (
            Path(__file__).resolve().parents[1]
            / "tasks"
            / "daily_quest_execution_matrix.json"
        )
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        row = next(
            item
            for item in matrix["objectives"]
            if item["objective_key"] == "personal_might_praise"
        )
        ownership = row["ownership_disposition"]
        self.assertEqual(ownership["catalog_owner"], "DQ-FLOW-PERSONAL-MIGHT-PRAISE")
        self.assertEqual(
            ownership["completion_attribution_owner"],
            "tasks.daily_quest.PersonalMightPraiseHandler",
        )
        self.assertIsNone(ownership["dispatch_authority"])
        self.assertEqual(ownership["claim_authority"], "aggregate_daily_claim")
        self.assertEqual(
            ownership["legacy_adapter"],
            "PERSONAL-MIGHT-PRAISE-BLISS-PILOT",
        )
        self.assertEqual(ownership["state"], "accepted_existing_observation_only")

if __name__ == "__main__":
    unittest.main()
