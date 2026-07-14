# Daily Quest execution matrix

Source of current status: `tasks/daily_quest_execution_matrix.json`.
Source of objective identity and retained observations:
`tasks/daily_quest_catalog.json`.

Catalog `implementation_status`, `live_validation_status`, `next_development_priority`, and
`policy_mode` fields remain legacy observation snapshots. They do not drive implementation,
promotion, registration, or scheduling. Matrix `scheduler_eligibility` is `false` for every
objective and support flow during this planning run.

## Admission rule

An objective enters catalog and matrix only with raw/lossless Bliss evidence or an inventory record
derived from such frames, positive Quest recognition, positive selected-Daily recognition, visible
objective-list text, non-Main classification, and exact source provenance. Backlog/plan prose,
generic task specifications, GnBots actions, unknown-tab OCR, and synthetic fixtures are
non-admitting evidence.

## Reconciled scope

Catalog contains 31 objective keys, derived only from the retained selected-Daily inventory.
Provenance audit: `tasks/daily_quest_provenance_audit.json`.

The audit excludes Vehicle Depot, Ultimate Challenge, Hunt Zombie, and Own Hero as
`PROVEN_MAIN_OBJECTIVE`; their retained raw frame shows Main Quest selected. It excludes
Headquarters attack/win as `DOCUMENTATION_ONLY` and Gather Food/Gathered Food as
`SYNTHETIC_ONLY`. None has a Daily matrix owner or implementation prompt.

## Offline support primitives

`DQ-FLOW-WORLD-STAMINA-ENGINE` is an objective-less shared primitive in matrix support flows.
`tasks/world_stamina.py` recognizes Bliss-native World routes and explicit stamina/AP budgets for
future Lair and gathering contracts. It performs no resource transaction, coordinate authorization,
runtime registration, or scheduler eligibility.

## Current objective state

| Key | Family / variant | Route | Matrix status | Promotion | Operator registration | Backlog |
|---|---|---|---|---|---|---|
| `upgrade_building` | building_upgrade / generic | `daily_go_to_building` | disabled | disabled | none | DQ-FLOW-BUILDING-UPGRADE |
| `join_hero_duel` | hero_duel / join | `daily_go_to_hero_duel` | disabled | disabled | none | DQ-FLOW-HERO-DUEL |
| `upgrade_tech` | tech_upgrade / research | `daily_go_to_tech` | disabled | disabled | none | DQ-FLOW-TECH-UPGRADE |
| `train_fighter` | training / Fighter | `daily_go_to_training` | disabled | disabled | none | DQ-FLOW-TRAINING |
| `train_rider` | training / Rider | `daily_go_to_training` | disabled | disabled | none | DQ-FLOW-TRAINING |
| `train_shooter` | training / Shooter | `daily_go_to_training` | disabled | disabled | none | DQ-FLOW-TRAINING |
| `train_vehicle` | training / Vehicle | `daily_go_to_training` | disabled | disabled | none | DQ-FLOW-TRAINING |
| `recruit_noahs_tavern` | recruitment / free single | `daily_go_to_noahs_tavern` | offline contract | evidence-gated | none | DQ-FLOW-RECRUITMENT |
| `upgrade_hero` | hero_upgrade / upgrade | `daily_go_to_hero` | disabled | disabled | none | DQ-FLOW-HERO-UPGRADE |
| `defeat_zombie_lair` | zombie_lair / lair | `daily_go_to_zombie_lair` | planned | evidence-gated | none | DQ-FLOW-ZOMBIE-LAIR |
| `consume_stamina` | stamina / consume | `daily_go_to_stamina_action` | disabled | disabled | none | DQ-FLOW-STAMINA |
| `consume_ap` | campaign_ap / Sweep, Auto Complete | `daily_go_to_campaign` | offline contract | evidence-gated | none | DQ-FLOW-CAMPAIGN-AP |
| `help_allies` | alliance_help / Help All, individual | `daily_go_to_speedup_help` | live validated | live validated | `alliance-help` | DQ-FLOW-ALLIANCE-HELP |
| `buy_box` | purchases / box | `daily_go_to_purchase` | disabled | disabled | none | DQ-FLOW-PURCHASES |
| `gather_wood` | gathering / wood, 30,000 | `daily_go_to_world` | planned | evidence-gated | none | DQ-FLOW-GATHERING |
| `gather_steel` | gathering / steel, 6,000 | `daily_go_to_world` | planned | evidence-gated | none | DQ-FLOW-GATHERING |
| `gather_gas` | gathering / gas, 1,500 | `daily_go_to_world` | planned | evidence-gated | none | DQ-FLOW-GATHERING |
| `boost_resource_building_output` | resource_building_boost / any resource | `daily_go_to_resource_building` | disabled | disabled | none | DQ-FLOW-RESOURCE-BOOST |
| `ruins_shop_purchase` | purchases / Ruins Shop | `daily_go_to_ruins_shop` | disabled | disabled | none | DQ-FLOW-PURCHASES |
| `rare_earth_shop_purchase` | purchases / Rare Earth Shop | `daily_go_to_rare_earth_shop` | disabled | disabled | none | DQ-FLOW-PURCHASES |
| `alliance_shop_purchase` | purchases / Alliance Shop | `daily_go_to_alliance_shop` | disabled | disabled | none | DQ-FLOW-PURCHASES |
| `speedup_using_items` | speedups / 180 minutes | `daily_go_to_speedup` | disabled | disabled | none | DQ-FLOW-SPEEDUP |
| `bioenhancer_research` | bioenhancer / one free | `daily_go_to_bioenhancer` | offline contract | evidence-gated | none | DQ-FLOW-BIOENHANCER |
| `craft_nanoweapon` | nanoweapon / Craft Weapon | `daily_go_to_nanoweapon` | offline contract | evidence-gated | none | DQ-FLOW-NANOWEAPON |
| `personal_might_praise` | personal_might_praise / one Praise | `daily_go_to_personal_might` | live validated | live validated | `praise` | DQ-FLOW-PERSONAL-MIGHT-PRAISE |
| `enhance_chip` | enhancement / Chip | `daily_go_to_chip` | offline contract | evidence-gated | none | DQ-FLOW-ENHANCE-CHIP |
| `enhance_module` | enhancement / Module | `daily_go_to_module` | offline contract | evidence-gated | none | DQ-FLOW-ENHANCE-MODULE |
| `enhance_gear` | enhancement / Gear | `daily_go_to_gear` | offline contract | evidence-gated | none | DQ-FLOW-ENHANCE-GEAR |
| `donate_alliance_tech` | donation / Alliance Tech | `daily_go_to_alliance_technology` | disabled | disabled | none | DQ-FLOW-DONATION |
| `supply_depot` | supply_depot / free collection | `daily_go_to_supply_depot` | offline contract | evidence-gated | none | DQ-FLOW-SUPPLY-DEPOT |
| `ruins_challenge` | challenges / Ruins | `daily_go_to_ruins_challenge` | disabled | disabled | none | DQ-FLOW-CHALLENGES |

## Support flows

Support flows are not objective keys and do not affect the catalog count:

- selected Daily-tab recognition and bounded inventory;
- generalized ordinary Daily row Claim;
- exact Personal Might Daily Claim;
- activity milestone-chest Claim;
- SQLite task-state persistence;
- one-pulse scheduler;
- future runtime-integration gate.

Praise, Personal Might Claim, individual Help, and Help All remain live-validated at their proven
effective boundaries. Existing operator registrations are recorded from checked-in `pnsctl.py`; no
offline contract is treated as registration. No scheduler eligibility is enabled.

## Per-entry contract

Every matrix entry supplies: route and recognizers; consequence/resource policy; completion target;
one-dispatch transaction boundary; semantic postcondition; fail-closed recovery; Daily
reconciliation; independent Claim behavior; dormant persistence; implementation/live/promotion
state; actual registration; scheduler state; existing implementation/tests; Bliss evidence;
GnBots provenance; missing work/evidence; product decisions; dependencies; backlog owner; and
standalone prompt path.
