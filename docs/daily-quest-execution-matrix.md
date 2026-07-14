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

`DQ-FLOW-STAMINA` uses `tasks/stamina_disabled.py` for counter-only replay and same-day arithmetic.
Current product policy blocks every stamina-spend dispatch; the objective remains unregistered and
scheduler-ineligible.

`DQ-FLOW-GATHERING` uses `tasks/gathering.py` for parameterized Wood, Steel, and Gas node/march
replay. Gather Food/Gathered Food remains excluded; live node evidence is still required for
promotion, and no runtime registration or scheduler eligibility is enabled.

`DQ-FLOW-TRAINING` uses `tasks/training_disabled.py` for four-way queue replay only. Product policy
blocks resource spending and training dispatch; all four objective rows remain disabled,
unregistered, and scheduler-ineligible.

`DQ-FLOW-BUILDING-UPGRADE` uses `tasks/building_upgrade_disabled.py` for generic building identity
and level replay only. Vehicle Depot remains Main-only; product policy blocks every upgrade
dispatch and the objective remains unregistered and scheduler-ineligible.

`DQ-FLOW-HERO-DUEL` uses `tasks/hero_duel_disabled.py` for event/Join/progress replay only. PvP
entry remains policy-disabled; the objective is unregistered and scheduler-ineligible.

`DQ-FLOW-TECH-UPGRADE` uses `tasks/tech_upgrade_disabled.py` for prerequisite/level replay only.
Research spend remains policy-disabled; the objective is unregistered and scheduler-ineligible.

`DQ-FLOW-HERO-UPGRADE` uses `tasks/hero_upgrade_disabled.py` for selected-hero/material/level
replay only. Hero material spend remains policy-disabled; the objective is unregistered and
scheduler-ineligible.

`DQ-FLOW-PURCHASES` uses `tasks/purchases_disabled.py` for Box, Ruins Shop, Rare Earth Shop, and
Alliance Shop offer/cost/item replay only. Currency spend remains policy-disabled; all four
objectives are unregistered and scheduler-ineligible.

`DQ-FLOW-DONATION` uses `tasks/donation_disabled.py` for Alliance Technology target/resource/count
replay only. Resource donation remains policy-disabled; the objective is unregistered and
scheduler-ineligible.

`DQ-FLOW-SPEEDUP` uses `tasks/speedup_disabled.py` for 180-minute timer/item replay only. Item
consumption remains policy-disabled; the objective is unregistered and scheduler-ineligible.

`DQ-FLOW-CHALLENGES` uses `tasks/challenge_disabled.py` for Ruins Challenge identity/cost/result
replay only. Challenge entry remains policy-disabled; Ultimate Challenge remains outside Daily
scope, and the Ruins objective is unregistered and scheduler-ineligible.

`DQ-FLOW-SUPPLY-DEPOT` uses `tasks/supply_depot.py` plus
`tasks/daily_supply_depot.py` for free Supply Depot collection replay bound to `supply_depot`.
Navigation evidence now proves selected Daily `supply_depot` at `0/5`, exact row-local Go
`(554,786)-(731,878)`, direct Supply Depot successor, four visible Free controls, first
free-single reward target `(35,1170)-(174,1261)`, no overlay, and bounded return to selected
Daily. Collection remains `EVIDENCE_ACQUIRED` but `POLICY_GATED`: game-day identity, approved
known-reward policy, collection postcondition, and Daily reconciliation remain unproven; no
registration or scheduler eligibility.

`DQ-FLOW-RECRUITMENT` uses `tasks/free_recruitment.py` plus
`tasks/daily_recruitment.py` for free Noah's Tavern single-recruit replay. The adapter requires
exactly enough one-pulse successors to reach Daily progress 5/5; fresh native target/result
evidence remains required, with no registration or scheduler eligibility.

`DQ-FLOW-BIOENHANCER` uses `tasks/bioenhancer.py` plus
`tasks/daily_bioenhancer.py` for one free Bioenhancer research replay bound to
`bioenhancer_research`. Navigation evidence now proves the selected row, direct Daily Go →
Bioenhancer Research successor, and immediate-frame Free Research 1x target
`[94,1133,345,1216]`; the separate Research 10x target is rejected. The flow is
`PRE_DISPATCH_READY` but remains matrix `EVIDENCE_GATED`: no research input occurred, positive
research/Daily 0→1 result is missing, current game-day identity is not independently observable,
and no registration or scheduler eligibility is enabled. See
`evidence/sessions/20260714-daily-flow-acquisition/bioenhancer-free-pre-dispatch.json`.

`DQ-FLOW-NANOWEAPON` uses `tasks/nanoweapon.py` plus `tasks/daily_nanoweapon.py` for one exact
Craft Weapon replay bound to `craft_nanoweapon`. Recipe/material/result evidence remains gated;
the objective is unregistered and scheduler-ineligible.

`DQ-FLOW-ENHANCE-GEAR` uses `tasks/enhancement.py` plus `tasks/daily_enhancement.py` for one
selected-Daily Gear enhancement replay. Exact equipped item, one-star material, and positive
successor evidence remain gated; Chip and Module stay separate variants, with no registration or
scheduler eligibility.

`DQ-FLOW-ENHANCE-CHIP` uses the same adapter with explicit Chip objective ownership and
`ENHANCE_CHIP` transaction semantics. Exact selected Chip, one-star material, and positive
successor evidence remain gated; the objective is unregistered and scheduler-ineligible.

`DQ-FLOW-ENHANCE-MODULE` uses the same adapter with explicit Module objective ownership and
`ENHANCE_MODULE` transaction semantics. Exact selected Module, one-star material, and positive
successor evidence remain gated; the objective is unregistered and scheduler-ineligible.

`DQ-FLOW-CAMPAIGN-AP` uses `tasks/campaign_ap.py` plus `tasks/daily_campaign_ap.py` for one
bounded Sweep/Auto Complete replay bound to `consume_ap`. Exact AP budget, delta, result, and
Daily progress remain evidence-gated; the objective is unregistered and scheduler-ineligible.

`DQ-FLOW-ZOMBIE-LAIR` uses `tasks/zombie_lair.py` plus `tasks/daily_zombie_lair.py` for one
allowlisted Lair join/result replay bound to `defeat_zombie_lair`. Level, march, stamina, and
defeat evidence remain gated; Hunt Zombie/Main wording stays excluded, with no registration or
scheduler eligibility.

`DQ-FLOW-RESOURCE-BOOST` uses `tasks/resource_boost_disabled.py` for resource-building identity,
resource, duration, cost, and boost-state replay only. Boost spending remains policy-disabled; the
objective is unregistered and scheduler-ineligible.

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
| `defeat_zombie_lair` | zombie_lair / lair | `daily_go_to_zombie_lair` | offline contract | evidence-gated | none | DQ-FLOW-ZOMBIE-LAIR |
| `consume_stamina` | stamina / consume | `daily_go_to_stamina_action` | disabled | disabled | none | DQ-FLOW-STAMINA |
| `consume_ap` | campaign_ap / Sweep, Auto Complete | `daily_go_to_campaign` | offline contract | evidence-gated | none | DQ-FLOW-CAMPAIGN-AP |
| `help_allies` | alliance_help / Help All, individual | `daily_go_to_speedup_help` | live validated | live validated | `alliance-help` | DQ-FLOW-ALLIANCE-HELP |
| `buy_box` | purchases / box | `daily_go_to_purchase` | disabled | disabled | none | DQ-FLOW-PURCHASES |
| `gather_wood` | gathering / wood, 30,000 | `daily_go_to_world` | offline contract | evidence-gated | none | DQ-FLOW-GATHERING |
| `gather_steel` | gathering / steel, 6,000 | `daily_go_to_world` | offline contract | evidence-gated | none | DQ-FLOW-GATHERING |
| `gather_gas` | gathering / gas, 1,500 | `daily_go_to_world` | offline contract | evidence-gated | none | DQ-FLOW-GATHERING |
| `boost_resource_building_output` | resource_building_boost / any resource | `daily_go_to_resource_building` | disabled | disabled | none | DQ-FLOW-RESOURCE-BOOST |
| `ruins_shop_purchase` | purchases / Ruins Shop | `daily_go_to_ruins_shop` | disabled | disabled | none | DQ-FLOW-PURCHASES |
| `rare_earth_shop_purchase` | purchases / Rare Earth Shop | `daily_go_to_rare_earth_shop` | disabled | disabled | none | DQ-FLOW-PURCHASES |
| `alliance_shop_purchase` | purchases / Alliance Shop | `daily_go_to_alliance_shop` | disabled | disabled | none | DQ-FLOW-PURCHASES |
| `speedup_using_items` | speedups / 180 minutes | `daily_go_to_speedup` | disabled | disabled | none | DQ-FLOW-SPEEDUP |
| `bioenhancer_research` | bioenhancer / one free | `daily_go_to_bioenhancer` | pre-dispatch ready | evidence-gated | none | DQ-FLOW-BIOENHANCER |
| `craft_nanoweapon` | nanoweapon / Craft Weapon | `daily_go_to_nanoweapon` | offline contract | evidence-gated | none | DQ-FLOW-NANOWEAPON |
| `personal_might_praise` | personal_might_praise / one Praise | `daily_go_to_personal_might` | live validated | live validated | `praise` | DQ-FLOW-PERSONAL-MIGHT-PRAISE |
| `enhance_chip` | enhancement / Chip | `daily_go_to_chip` | offline contract | evidence-gated | none | DQ-FLOW-ENHANCE-CHIP |
| `enhance_module` | enhancement / Module | `daily_go_to_module` | offline contract | evidence-gated | none | DQ-FLOW-ENHANCE-MODULE |
| `enhance_gear` | enhancement / Gear | `daily_go_to_gear` | offline contract | evidence-gated | none | DQ-FLOW-ENHANCE-GEAR |
| `donate_alliance_tech` | donation / Alliance Tech | `daily_go_to_alliance_technology` | disabled | disabled | none | DQ-FLOW-DONATION |
| `supply_depot` | supply_depot / free collection | `daily_go_to_supply_depot` | evidence acquired / policy-gated | policy-gated | none | DQ-FLOW-SUPPLY-DEPOT |
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
