# Daily Quest execution matrix

Source of current status: `tasks/daily_quest_execution_matrix.json`.
Source of objective identity and retained observations:
`tasks/daily_quest_catalog.json`.

Catalog `implementation_status`, `live_validation_status`, `next_development_priority`, and
`policy_mode` fields remain legacy observation snapshots. They do not drive implementation,
promotion, registration, or scheduling. Matrix `scheduler_eligibility` is `false` for every
objective and support flow. The eight reconciled gameplay identities below are also unregistered
and scheduler-ineligible; offline contracts and retained evidence do not authorize runtime input.

## Admission rule

An objective enters catalog and matrix only with raw/lossless Bliss evidence or an inventory record
derived from such frames, positive Quest recognition, positive selected-Daily recognition, visible
objective-list text, non-Main classification, and exact source provenance. Backlog/plan prose,
generic task specifications, GnBots actions, unknown-tab OCR, and synthetic fixtures are
non-admitting evidence.

## Reconciled scope

Catalog contains 31 objective keys, derived only from the retained selected-Daily inventory.
Provenance audit: `tasks/daily_quest_provenance_audit.json`.

The audit excludes Vehicle Depot, Ultimate Challenge, Hunt Zombie, and Own Hero from the
selected-Daily row catalog as `PROVEN_MAIN_OBJECTIVE`; their retained raw frame shows Main Quest
selected. It excludes Headquarters attack/win as `DOCUMENTATION_ONLY` and Gather Food/Gathered
Food as `SYNTHETIC_ONLY`. Ultimate Challenge nevertheless has a separately approved, reset-bound
Daily gameplay-flow identity. That identity does not manufacture a selected-Daily row or alter the
31-key catalog.

## Reconciled gameplay-flow identities

| Identity | Ownership | Current boundary | Registration / scheduler |
| --- | --- | --- | --- |
| `NANOWEAPON-BLUESTACKS-INTEGRATION` | Daily: one Normal Craft per reset | legacy offline replay; evidence required | none / disabled |
| `NANO-MATERIAL-PRODUCTION-MAINTENANCE` | independent maintenance | contract only; evidence required | none / disabled |
| `RECRUITMENT-BLUESTACKS-INTEGRATION` | Daily: five Basic free recruits | retained mechanics/navigation + offline controller; production replay required | none / disabled |
| `RECRUITMENT-FREE-ATTEMPT-MAINTENANCE` | independent three-tab maintenance | retained mechanics/navigation + offline controller; production replay required | none / disabled |
| `CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION` | Campaign AP maintenance | retained navigation/controller/BlueStacks mechanics; production replay required | none / disabled |
| `ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION` | Daily: one verified Flee per reset | navigation/idempotency only; execution evidence required | none / disabled |
| `ZOMBIE-LAIR-BLUESTACKS-INTEGRATION` | Daily: first eligible join | legacy offline replay; Home-notification evidence required | none / disabled |
| `ZOMBIE-LAIR-HOME-MAINTENANCE` | independent Home pulse | World/stamina primitives only; evidence required | none / disabled |

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
replay only. Ruins entry remains policy-disabled. Ultimate Challenge is not a Ruins variant or a
selected-Daily row: its dedicated Daily identity follows Campaign → Ultimate Challenge →
Challenge → Hero Lineup Challenge → Exit → Flee, consumes no resource, and remains unregistered,
scheduler-ineligible, and evidence-gated.

`DQ-FLOW-SUPPLY-DEPOT` uses `tasks/supply_depot.py` plus
`tasks/daily_supply_depot.py` for free Supply Depot collection replay bound to `supply_depot`.
Navigation evidence now proves selected Daily `supply_depot` at `0/5`, exact row-local Go
`(554,786)-(731,878)`, direct Supply Depot successor, four visible Free controls, first
free-single reward target `(35,1170)-(174,1261)`, no overlay, and bounded return to selected
Daily. Collection remains `EVIDENCE_ACQUIRED` but `POLICY_GATED`: game-day identity, approved
known-reward policy, collection postcondition, and Daily reconciliation remain unproven; no
registration or scheduler eligibility.

`DQ-FLOW-RECRUITMENT` retains `tasks/free_recruitment.py`, `tasks/daily_recruitment.py`, and the
integrated Noah's Tavern recognizer/controller/route. Daily completion belongs to five Basic free
singles in the current reset, one per exact ten-minute availability window. Independent maintenance
inspects Basic, Int., and Advanced, uses every currently available free single, and tracks the
ten-minute, 24-hour, and 48-hour cooldowns separately. Paid, premium, item-backed, 10x, and
ambiguous controls are prohibited; cooling-down/exhausted tabs defer explicitly; Home is required.

The retained 2026-07-16 Computer Use session is valid gameplay/mechanics and semantic navigation
evidence for Home → Tavern, three Basic, one Int., one Advanced, observed cooldowns, safe result
closure, Daily 5/5, no Claim input, and Home return. Its semantic frame identifiers are not
hash-bound screenshots, a consequential journal, or a production-controller attempt record, so a
production-grade positive replay remains required. Registration and scheduler eligibility remain
disabled.

`DQ-FLOW-BIOENHANCER` uses `tasks/bioenhancer.py` plus
`tasks/daily_bioenhancer.py` for one free Bioenhancer research replay bound to
`bioenhancer_research`. Navigation evidence now proves the selected row, direct Daily Go →
Bioenhancer Research successor, and immediate-frame Free Research 1x target
`[94,1133,345,1216]`; the separate Research 10x target is rejected. The flow is
`PRE_DISPATCH_READY` but remains matrix `EVIDENCE_GATED`: no research input occurred, positive
research/Daily 0→1 result is missing, current game-day identity is not independently observable,
and no registration or scheduler eligibility is enabled. See
`evidence/sessions/20260714-daily-flow-acquisition/bioenhancer-free-pre-dispatch.json`.

`DQ-FLOW-NANOWEAPON` retains `tasks/nanoweapon.py` plus `tasks/daily_nanoweapon.py` as legacy
one-craft replay support. The final Daily contract uses Normal Craft only, claims a completed weapon
on entry, requires exactly 100 nano parts plus an enabled Craft control, permits at most one start
per game-day/reset, and uses an exact 12-hour duration. Exclusive Craft and same-reset additional
starts are prohibited; insufficient parts or a disabled control defer without consuming anything.

`NANO-MATERIAL-PRODUCTION-MAINTENANCE` is a distinct non-Daily identity. It consumes no base
resources, boxes, currency, or items; allows one active production; uses an exact six-hour duration;
claims and restarts when complete; records/refreshes the due time when active; starts when idle; and
returns Home. Both identities remain unregistered, scheduler-ineligible, and evidence-gated.

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

`DQ-FLOW-CAMPAIGN-AP` reuses the retained Campaign destination, controller, vision, and Auto Battle
work. Maximum AP is 120 and regeneration is exactly one AP per 360 seconds. Approved stages are
`1-15-9` at 14 AP, `1-20-9` at 16 AP, and `2-2-9` at 20 AP. The configured stage must be navigated
to and its displayed identity/AP cost verified on every entry. Execute as many safe whole runs as
current AP permits using Auto Battle only; Sweep, Blitz, Auto Complete, and every refill are
prohibited. Expected AP and recovery time may be tracked, but displayed AP/cost remains mandatory
before execution. Insufficient AP defers; Home is required. Retained BlueStacks mechanics and
offline controller replay are not a production-controller positive replay, and registration and
scheduler eligibility remain disabled.

`DQ-FLOW-ZOMBIE-LAIR` retains `tasks/zombie_lair.py`, `tasks/daily_zombie_lair.py`, and the shared
World/stamina primitives as offline support, but no longer starts from a static Daily row. The
Home-notification maintenance identity accepts levels 30–55, rejects level 60, budgets exactly 28
stamina per Quick Join, and joins up to
`min(eligible_lair_count, floor(current_stamina / 28))`. No notification and insufficient stamina
are explicit defer/no-op outcomes; below 28 stamina, recovery is estimated before another pulse.
Refills are prohibited and any refill prompt is cancelled or left safely. The first successful
eligible join owns Daily completion; maintenance continues after Daily completion and returns to
Home or a recognized safe Home-equivalent. Native notification/result/refill evidence and a
production replay remain required; registration and scheduler eligibility remain disabled.

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
| `recruit_noahs_tavern` | recruitment / five Basic free singles | `daily_go_to_noahs_tavern` | retained offline/integrated contract | evidence-gated production replay | none | DQ-FLOW-RECRUITMENT |
| `upgrade_hero` | hero_upgrade / upgrade | `daily_go_to_hero` | disabled | disabled | none | DQ-FLOW-HERO-UPGRADE |
| `defeat_zombie_lair` | zombie_lair / first eligible Home-notification join | `home_lair_notification` | legacy offline support | evidence-gated | none | DQ-FLOW-ZOMBIE-LAIR |
| `consume_stamina` | stamina / consume | `daily_go_to_stamina_action` | disabled | disabled | none | DQ-FLOW-STAMINA |
| `consume_ap` | campaign_ap / configured-stage Auto Battle | `daily_go_to_campaign` | retained controller replay | evidence-gated production replay | none | DQ-FLOW-CAMPAIGN-AP |
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
| `craft_nanoweapon` | nanoweapon / one Normal Craft per reset | `daily_go_to_nanoweapon` | legacy offline support | evidence-gated | none | DQ-FLOW-NANOWEAPON |
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

Independent gameplay maintenance identities are support flows, not new catalog objective keys:

- `NANO-MATERIAL-PRODUCTION-MAINTENANCE`;
- `RECRUITMENT-FREE-ATTEMPT-MAINTENANCE`;
- `ZOMBIE-LAIR-HOME-MAINTENANCE`.

`ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION` is a reset-bound Daily gameplay identity outside
the selected-Daily row catalog. The complete reconciled eight-identity coverage is recorded in
`tasks/flow_delivery_coverage.json` and `docs/flow_delivery_coverage.md`.

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
