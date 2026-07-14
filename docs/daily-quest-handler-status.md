# Daily Quest handler status

Current status authority: `tasks/daily_quest_execution_matrix.json`.
Objective identity authority: `tasks/daily_quest_catalog.json`.

Catalog status values are retained legacy observation snapshots only. This file mirrors matrix
status; it must not become an independent status source. All scheduler eligibility is false.

## Live-validated

- `help_allies`: individual Help and actual lower Help All; canonical route
  `daily_go_to_speedup_help`; existing operator task `alliance-help`.
- `personal_might_praise`: exact current-frame Praise route; existing operator task `praise`.
- Support flow `personal_might_daily_claim`: exact row-local Claim; existing operator task
  `personal-might-claim`.

These registrations are preserved. They do not imply scheduler eligibility or unattended
promotion. Praise completion stops before Claim.

## Offline implemented

- Generalized Daily Claim contract: `tasks/available_daily_claim.py`.
- Milestone Claim contract: `tasks/activity_milestones.py`.
- Supply Depot free contract: `tasks/supply_depot.py`.
- Free Recruitment contract: `tasks/free_recruitment.py`.
- Bioenhancer free-research contract: `tasks/bioenhancer.py`.
- Nanoweapon Craft Weapon contract: `tasks/nanoweapon.py`.
- Gear/Chip/Module shared enhancement contract: `tasks/enhancement.py` (Gear and Chip variants
  complete; Module remains downstream).
- Task-state and one-pulse scheduler contracts: `tasks/scheduler.py`,
  `safe_action_core/task_state.py`, and `safe_action_core/store.py`.

These contracts remain unregistered and evidence-gated where matrix says so.

## Evidence-gated planned flows

`bioenhancer_research`, `recruit_noahs_tavern`, `supply_depot`, `craft_nanoweapon`,
`consume_ap`, `defeat_zombie_lair`, `gather_wood`, `gather_steel`, `gather_gas`,
`enhance_gear`, `enhance_chip`, and `enhance_module` require fresh Bliss-native target,
cost/resource, and positive-postcondition evidence before promotion.

## Policy-disabled flows

`upgrade_building`, `upgrade_tech`, `train_fighter`, `train_rider`, `train_shooter`,
`train_vehicle`, `upgrade_hero`, `consume_stamina`, `buy_box`, all shop purchases,
`boost_resource_building_output`, `donate_alliance_tech`, `speedup_using_items`,
`ruins_challenge`, and `join_hero_duel` remain offline-only, unregistered, and
scheduler-ineligible.

The provenance audit excludes Vehicle Depot, Ultimate Challenge, Hunt Zombie, and Own Hero as
Main-only; Gather Food/Gathered Food as synthetic-only; and Headquarters attack/win as
documentation-only. These candidates have no Daily handler owner, prompt, or matrix entry.

## Separation rules

- Main Quest Claim is explicitly excluded from active scope.
- Generic Daily row Claim, Personal Might Claim, and milestone Claim are separate flows.
- Objective completion never authorizes Claim.
- Static GnBots geometry and calibration output never authorize input.
- Existing runtime registrations are not inferred from offline modules.
- No new runtime registration, scheduler eligibility, worker wiring, live task-state row, lease,
  journal migration, ADB operation, or gameplay input occurs in this planning run.
