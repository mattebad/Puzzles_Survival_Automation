from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import unittest

from tasks.contracts import TaskOutcome
from tasks.world_stamina import (
    WorldStaminaObservation,
    world_resource_budget_authorizeable,
    world_route_authorizeable,
    world_route_postcondition_verified,
    world_stamina_replay_one_pulse,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase_e_world_stamina_observations.json"


def load_fixture(name: str) -> WorldStaminaObservation:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    payload["target_roi"] = tuple(payload["target_roi"])
    payload["panel_bounds"] = tuple(payload["panel_bounds"])
    payload["evidence_refs"] = tuple(payload["evidence_refs"])
    return WorldStaminaObservation(**payload)


class WorldStaminaPrimitiveTests(unittest.TestCase):
    def test_route_family_ownership_is_explicit(self):
        lair = load_fixture("lair_route")
        resource = load_fixture("resource_route")
        self.assertTrue(
            world_route_authorizeable(lair, destination_kind="ZOMBIE_LAIR")
        )
        self.assertFalse(
            world_route_authorizeable(lair, destination_kind="RESOURCE_NODE")
        )
        self.assertTrue(
            world_route_authorizeable(resource, destination_kind="RESOURCE_NODE")
        )
        self.assertFalse(
            world_route_authorizeable(resource, destination_kind="ZOMBIE_LAIR")
        )

    def test_resource_budget_requires_current_and_policy_bounds(self):
        observation = load_fixture("lair_route")
        self.assertTrue(
            world_resource_budget_authorizeable(
                observation, resource_name="STAMINA", requested_cost=20
            )
        )
        for resource_name, requested_cost in (
            ("STAMINA", 21),
            ("STAMINA", 81),
            ("AP", 10),
            ("STAMINA", 0),
        ):
            self.assertFalse(
                world_resource_budget_authorizeable(
                    observation,
                    resource_name=resource_name,
                    requested_cost=requested_cost,
                )
            )

    def test_main_static_stale_and_uncertain_states_fail_closed(self):
        self.assertFalse(
            world_route_authorizeable(
                load_fixture("main_negative"), destination_kind="ZOMBIE_LAIR"
            )
        )
        self.assertFalse(
            world_route_authorizeable(
                load_fixture("static_reference_negative"),
                destination_kind="ZOMBIE_LAIR",
            )
        )
        observation = load_fixture("lair_route")
        for changes in (
            {"refill_visible": True},
            {"overlay_state": "unknown"},
            {"target_roi": (10, 10, 100, 80)},
            {"recognized": False},
        ):
            self.assertFalse(
                world_route_authorizeable(
                    replace(observation, **changes),
                    destination_kind="ZOMBIE_LAIR",
                )
            )

    def test_route_postcondition_requires_stable_same_day_state(self):
        before = load_fixture("lair_route")
        self.assertTrue(
            world_route_postcondition_verified(
                before, before, destination_kind="ZOMBIE_LAIR"
            )
        )
        self.assertTrue(
            world_route_postcondition_verified(
                before, replace(before), destination_kind="ZOMBIE_LAIR"
            )
        )
        self.assertFalse(
            world_route_postcondition_verified(
                before,
                replace(before, game_day_id="next-day"),
                destination_kind="ZOMBIE_LAIR",
            )
        )
        self.assertFalse(
            world_route_postcondition_verified(
                before,
                replace(before, current_resource=79),
                destination_kind="ZOMBIE_LAIR",
            )
        )

    def test_replay_is_pure_and_has_no_runtime_action(self):
        before = load_fixture("lair_route")
        prepared = world_stamina_replay_one_pulse(
            before, destination_kind="ZOMBIE_LAIR"
        )
        self.assertEqual(prepared.outcome, TaskOutcome.PROGRESS)
        done = world_stamina_replay_one_pulse(
            before, replace(before), destination_kind="ZOMBIE_LAIR"
        )
        self.assertEqual(done.outcome, TaskOutcome.DONE)
        self.assertEqual(
            done.completion_key,
            "world-route:ZOMBIE_LAIR:lair-level-1:stable",
        )


if __name__ == "__main__":
    unittest.main()
