"""One active runtime profile; Bliss-tagged or Bliss-profile evidence is rejected everywhere."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from tasks import (
    activity_milestones,
    bioenhancer,
    building_upgrade_disabled,
    challenge_disabled,
    donation_disabled,
    free_recruitment,
    gathering,
    hero_duel_disabled,
    hero_upgrade_disabled,
    nanoweapon,
    purchases_disabled,
    resource_boost_disabled,
    speedup_disabled,
    stamina_disabled,
    supply_depot,
    tech_upgrade_disabled,
    training_disabled,
    world_stamina,
    zombie_lair,
)
from tasks.profile import BLUESTACKS_NATIVE_TARGET_PROVENANCE

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
# Immutable record of the retired Bliss profile; it is only ever a negative case here.
RETIRED_BLISS_PROFILE_ID = json.loads(
    (ROOT / "evidence/sessions/20260712-m6-dq-bootstrap/assets/asset-manifest.json").read_text(encoding="utf-8")
)["profile_id"]
RETIRED_BLISS_PROVENANCE = "bliss-native"


def _synthetic_hero_duel_observation():
    return hero_duel_disabled.HeroDuelObservation(
        screen_state="hero_duel_overview",
        source_frame_sha256="b" * 64,
        event_identity="synthetic-hero-duel-survival",
        event_variant=hero_duel_disabled.HERO_DUEL_SURVIVAL,
        event_active=True,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        evidence_refs=("synthetic:profile-hero-duel",),
    )


def _synthetic_wali_upgrade_observation():
    return hero_upgrade_disabled.HeroUpgradeObservation(
        screen_state="HERO", hero_identity="Wali", hero_selected=True,
        current_level=5, evolution_cap=10,
        material_costs={"ANTISERUM": 100}, material_balances={"ANTISERUM": 500},
        target_identity="hero-upgrade", target_roi=(100, 1140, 350, 1220),
        panel_bounds=(44, 820, 756, 1250), control_class="UPGRADE",
        game_day_id="synthetic-profile-day", confirmed_upgrades=0,
        material_rows_complete=True, stable_selected_state=True,
        normal_upgrade_visible=True, normal_single_upgrade=True,
        target_provenance=BLUESTACKS_NATIVE_TARGET_PROVENANCE,
        source_frame_sha256="c" * 64, evidence_refs=("synthetic:profile-wali",),
    )


def _load(filename: str | None, name: str, observation_type):
    if filename is None:
        if observation_type is hero_upgrade_disabled.HeroUpgradeObservation:
            return _synthetic_wali_upgrade_observation()
        return _synthetic_hero_duel_observation()
    payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))["observations"][name]
    for key in ("target_roi", "panel_bounds", "evidence_refs"):
        if key in payload:
            payload[key] = tuple(payload[key])
    if observation_type is tech_upgrade_disabled.TechUpgradeObservation:
        payload["prerequisite_evidence"] = tuple(payload["prerequisite_evidence"])
        payload["resource_rows"] = tuple(
            tech_upgrade_disabled.ResearchResourceRow(**row)
            for row in payload["resource_rows"]
        )
    return observation_type(**payload)


def _tech_upgrade_profile_authorizeable(observation):
    listing = _load(
        "phase_e_disabled_tech_upgrade_observations.json",
        "list",
        tech_upgrade_disabled.RecommendedResearchListObservation,
    )
    return tech_upgrade_disabled.tech_upgrade_authorizeable(observation, listing)


# (fixture file, fixture name, observation type, predicate)
CASES = {
    "activity_milestones": ("phase_e_activity_milestone_observations.json", "ready_synthetic",
                            activity_milestones.ActivityMilestoneObservation,
                            activity_milestones.activity_milestone_authorizeable),
    "bioenhancer": ("phase_e_bioenhancer_observations.json", "free_synthetic",
                    bioenhancer.BioenhancerObservation, bioenhancer.bioenhancer_authorizeable),
    "building_upgrade": ("phase_e_disabled_building_upgrade_observations.json", "generic_valid",
                         building_upgrade_disabled.BuildingUpgradeObservation,
                         building_upgrade_disabled.building_upgrade_authorizeable),
    "challenge": ("phase_e_disabled_challenge_observations.json", "valid",
                  challenge_disabled.ChallengeObservation, challenge_disabled.challenge_authorizeable),
    "donation": ("phase_e_disabled_donation_observations.json", "valid",
                 donation_disabled.DonationObservation, donation_disabled.donation_authorizeable),
    "free_recruitment": ("phase_e_free_recruitment_observations.json", "free_synthetic",
                         free_recruitment.FreeRecruitmentObservation,
                         free_recruitment.free_recruitment_authorizeable),
    "gathering": ("phase_e_gathering_observations.json", "wood_valid",
                  gathering.GatheringObservation, gathering.gathering_authorizeable),
    "hero_duel": (None, "current_survival",
                  hero_duel_disabled.HeroDuelObservation,
                  hero_duel_disabled.hero_duel_current_survival),
    "hero_upgrade": (None, "current_wali",
                     hero_upgrade_disabled.HeroUpgradeObservation,
                     hero_upgrade_disabled.hero_upgrade_authorizeable),
    "nanoweapon": ("phase_e_nanoweapon_observations.json", "normal_craft_synthetic",
                   nanoweapon.NanoweaponObservation, nanoweapon.nanoweapon_authorizeable),
    "purchases": ("phase_e_disabled_purchase_observations.json", "valid_box",
                  purchases_disabled.PurchaseObservation, purchases_disabled.purchase_authorizeable),
    "resource_boost": ("phase_e_disabled_resource_boost_observations.json", "valid",
                       resource_boost_disabled.ResourceBoostObservation,
                       resource_boost_disabled.resource_boost_authorizeable),
    "speedup": ("phase_e_disabled_speedup_observations.json", "valid",
                speedup_disabled.SpeedupObservation, speedup_disabled.speedup_authorizeable),
    "stamina": ("phase_e_disabled_stamina_observations.json", "daily_counter_synthetic",
                stamina_disabled.DisabledStaminaObservation, stamina_disabled.stamina_counter_authorizeable),
    "supply_depot": ("phase_e_supply_depot_observations.json", "free_synthetic",
                     supply_depot.SupplyDepotObservation, supply_depot.supply_depot_authorizeable),
    "tech_upgrade": ("phase_e_disabled_tech_upgrade_observations.json", "valid",
                     tech_upgrade_disabled.TechUpgradeObservation,
                     _tech_upgrade_profile_authorizeable),
    "training": ("phase_e_disabled_training_observations.json", "fighter_valid",
                 training_disabled.TrainingObservation, training_disabled.training_queue_authorizeable),
    "zombie_lair": ("phase_e_zombie_lair_observations.json", "lair_synthetic",
                    zombie_lair.ZombieLairObservation, zombie_lair.zombie_lair_authorizeable),
}


class ActiveProfileTests(unittest.TestCase):

    def test_native_fixtures_authorize_and_bliss_evidence_is_rejected(self):
        for name, (filename, fixture, observation_type, predicate) in CASES.items():
            observation = _load(filename, fixture, observation_type)
            with self.subTest(name=name, case="bluestacks"):
                self.assertEqual(observation.target_provenance, BLUESTACKS_NATIVE_TARGET_PROVENANCE)
                self.assertTrue(predicate(observation))
            for case, changes in (
                ("bliss provenance", {"target_provenance": RETIRED_BLISS_PROVENANCE}),
                ("bliss profile", {"runtime_profile_id": RETIRED_BLISS_PROFILE_ID}),
                ("both", {"target_provenance": RETIRED_BLISS_PROVENANCE,
                          "runtime_profile_id": RETIRED_BLISS_PROFILE_ID}),
            ):
                with self.subTest(name=name, case=case):
                    self.assertFalse(predicate(replace(observation, **changes)))

    def test_world_route_rejects_bliss_evidence(self):
        observation = _load("phase_e_world_stamina_observations.json", "lair_route",
                            world_stamina.WorldStaminaObservation)
        self.assertTrue(world_stamina.world_route_authorizeable(observation, destination_kind="ZOMBIE_LAIR"))
        for changes in (
            {"target_provenance": RETIRED_BLISS_PROVENANCE},
            {"runtime_profile_id": RETIRED_BLISS_PROFILE_ID},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(world_stamina.world_route_authorizeable(
                    replace(observation, **changes), destination_kind="ZOMBIE_LAIR"))


if __name__ == "__main__":
    unittest.main()
