# Portfolio requirements inventory

This inventory is a non-authorizing planning index. It does not register a handler, enable a
scheduler, promote a flow, authorize input, or replace a gameplay contract.

## Separate identities

Keep these identities separate in code, persistence, evidence, and policy:

- observation and navigation;
- claims and rewards;
- cooldown and reset maintenance;
- queue and facility maintenance;
- resources and progression;
- AP and stamina;
- marches and world-map actions;
- combat and challenges;
- shops and purchases;
- manual-only account/runtime states.

Evidence from one identity cannot promote another identity.

## Requirement families

| Family | Offline requirement | Current authority |
| --- | --- | --- |
| Observation/navigation | Fresh native provenance, profile/freshness, Home/Atlas localization, target binding, safe exit, successor proof | Shared perception and existing Home/Campaign semantics; no production registration |
| Claims | Identify the exact local claim and receipt/result; never confuse Go, reward, or purchase controls | Disabled progression family |
| Cooldown/reset | Bind reset identity once per session; use UTC epoch deadlines at the service boundary | Scheduler state is disabled |
| Queue maintenance | Track queue identity, timer, capacity, and completion without inventing a dispatch | Disabled progression family |
| Resources/progression | Record resource/material deltas and reserve/cap effects independently | Product decisions remain flow-specific |
| AP/stamina | Keep AP and stamina ledgers separate; no refill fallback | Campaign AP policy forbids refill; stamina family disabled |
| Marches | Track slot, target, return estimate, and occupancy separately from world navigation | Gathering and lair policy remain unresolved/disabled |
| Combat/challenges | Separate challenge setup, combat dispatch, result reconciliation, and chest/reward claims | No automatic production authority |
| Shops | Treat Cash Mall, Exchange, and paid offers as unsupported/manual-only | No purchase handler |
| Manual-only | Login, tutorial, CAPTCHA, account selection, credentials, and ambiguous identity stop automation | Permanently manual-only |

## Known stale or unresolved requirements

- Zombie level evidence has a stale `20 → 28` conflict; it is not a scheduler or action
  authorization.
- Nanoweapon requires `100` parts and a `43200` second production cadence; maintenance and
  daily collection remain separate identities.
- Material Production uses a `21600` second cadence.
- Gathering target/resource-node/march policy is unresolved and remains disabled.
- Conflicting proof states remain `evidence_required` until independently reconciled.
- Progression families (purchases, donations, speedups, upgrades, and unsupported resource
  transactions) remain disabled pending their own policy and evidence.

## Authority boundaries

The queue and gameplay contracts remain authoritative for flow semantics and historical evidence.
The disabled production registry owns only handler/profile/mode/registration/scheduler eligibility.
The automation service composes those authorities; it does not copy queue history, contract policy,
evidence state, or runner definitions.

## Daily Quest Portfolio reconciliation — REC-D01

This checkpoint reconciles current Daily identity and product policy only. It implements no gameplay
behavior, selects no queue flow, freezes no execution manifest, authorizes no runtime input, and
changes no registration, scheduler, composition, M6, or Bliss state. The catalog, execution matrix,
and product policy are static planning facts: `can_claim=false`, `can_reserve=false`,
`can_enable=false`, `can_dispatch=false`, and `runtime_authority=false`.

### Singular authority and exact recovery ownership

- `tasks/daily_quest_catalog.json` owns admitted Daily identity. Only current selected-Daily native
  objective-list evidence may admit an objective; historical screenshots, prose, and synthetic
  fixtures cannot do so.
- `tasks/daily_quest_execution_matrix.json#portfolio_reconciliation` owns the exact recovery owner,
  current state, preserved historical owner/state/missing proof, and dependency order. Capability
  snapshots in the per-objective rows remain non-authorizing and retain their legacy backlog owners.
- `tasks/flow_delivery_product_policy.json` owns route-local product controls. It cannot claim,
  reserve, enable, register, schedule, or dispatch a runtime occurrence.
- `tasks/flow_delivery_queue.json#portfolio_staging` remains an order/blocker mirror only;
  `active_flow_id` remains `null`.

The complete one-owner table is:

| Daily catalog key | Recovery owner | Preserved matrix state |
| --- | --- | --- |
| `upgrade_building` | `REC-P06` | `DEFERRED_NOT_CURRENT_PORTFOLIO` |
| `join_hero_duel` | `REC-P05` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `upgrade_tech` | `REC-P07` | `DEFERRED_NOT_CURRENT_PORTFOLIO` |
| `train_fighter` | `REC-R06` | `ACCEPTED_EXISTING` |
| `train_rider` | `REC-R07` | `ACCEPTED_EXISTING` |
| `train_shooter` | `REC-R08` | `ACCEPTED_EXISTING` |
| `train_vehicle` | `REC-R09` | `ACCEPTED_EXISTING` |
| `recruit_noahs_tavern` | `REC-D07` | `ACCEPTED_EXISTING` |
| `upgrade_hero` | `REC-P04` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `defeat_zombie_lair` | `REC-R19` | `DEFERRED_EXPLICIT` |
| `consume_stamina` | `REC-R19` | `DEFERRED_NOT_CURRENT_PORTFOLIO` |
| `consume_ap` | `REC-R11` | `ACCEPTED_EXISTING` |
| `help_allies` | `REC-D08` | `ACCEPTED_EXISTING` |
| `buy_box` | `REC-P12` | `DEFERRED_NOT_CURRENT_PORTFOLIO` |
| `gather_wood` | `REC-R17` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `gather_steel` | `REC-R17` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `gather_gas` | `REC-R18` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `boost_resource_building_output` | `REC-P10` | `DEFERRED_NOT_CURRENT_PORTFOLIO` |
| `ruins_shop_purchase` | `REC-P01` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `rare_earth_shop_purchase` | `REC-P02` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `alliance_shop_purchase` | `REC-P03` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `speedup_using_items` | `REC-P09` | `DEFERRED_EXPLICIT` |
| `bioenhancer_research` | `REC-D06` | `ACCEPTED_EXISTING` |
| `craft_nanoweapon` | `REC-R15` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `personal_might_praise` | `REC-D09` | `ACCEPTED_EXISTING` |
| `enhance_chip` | `REC-R04` | `EVIDENCE_REQUIRED` |
| `enhance_module` | `REC-R05` | `EVIDENCE_REQUIRED` |
| `enhance_gear` | `REC-R03` | `EVIDENCE_REQUIRED` |
| `donate_alliance_tech` | `REC-P08` | `IMPLEMENTATION_AND_EVIDENCE_REQUIRED` |
| `supply_depot` | `REC-D10` | `EVIDENCE_REQUIRED` |
| `ruins_challenge` | `REC-R12` | `ACCEPTED_EXISTING` |

The table is a reconciliation mapping, not a dispatch-owner registry. Every row has a null dispatch
authority; shared recovery ownership (for example REC-R19 for Zombie Lair and Stamina, or REC-R17
for Wood and Steel) does not create a duplicate dispatch owner. No row is promoted by this checkpoint.

### Identity and completion boundaries

- **Ultimate:** the non-catalog Daily identity is `Join` owned by `REC-D05`; `Clear Ultimate
  Challenge Stage` is Main identity and never Daily proof. Campaign AP remains the separate `REC-R11`
  identity. Ultimate Daily Join is not a catalog key and cannot inherit Campaign AP ownership.
- **Praise:** Nova free Praise is a direct product action. Selected-Daily Personal Might Praise is
  a separate completion-attribution identity owned by `REC-D09`; Nova does not dispatch, claim, or
  transfer Personal Might ownership.
- **Resource Item:** `use_resource_item` is a non-catalog `REC-R02` candidate. It has no Daily
  ownership until both current direct-resource transaction evidence and current selected-Daily
  objective-list evidence are present. Direct item proof alone is insufficient.
- **Gather Food:** `gather_food` is the non-catalog `REC-R16` proving slice and is explicitly excluded
  from Daily admission. Food proving evidence does not create a Daily route or owner.
- **Training and marches:** completion requires a current positive postcondition for the configured
  action. A queue entry, timer, outbound march, return projection, or dispatch receipt alone never
  proves completion.
- **Supply Depot:** only positively recognized zero-cost `Free` controls are eligible. Stop when
  `Free` disappears. Permissions, panel access, or collection eligibility never infer Daily `5/5`;
  independent positive Daily progress is required.

### Cost and control policy

Premium/cash purchases, paid controls, ambiguous controls, refill, `10x`, and item-backed substitutes
are prohibited. Route-approved resource, AP, and stamina effects are not globally forbidden; each
remains governed by its own route-specific R/P ticket and current evidence. Unknown cost, target,
level, resource, material, consequence, or successor fails closed. BuyBox `REC-P12` is distinct from
ResourceBuildingBoost `REC-P10`; no purchase or boost dispatch is implied.

### Historical reconciliation retained

The four historical portrait iOS screenshots `IMG_5076.PNG` through `IMG_5079.PNG` contain 32 visible
Daily rows and remain design references only. The matrix preserves each prior owner, state, and
missing proof beside its new REC owner. In particular, historical `use_resource_item` is retained
as a direct-resource candidate with an unresolved two-proof Daily boundary; historical Gather Food
remains synthetic-only and excluded; historical Ultimate `Join` is non-catalog and distinct from Main
`Clear`; and current selected-Daily evidence admits `upgrade_tech` and `buy_box` despite their absence
from those screenshots.

### Evidence and deferrals

No item from this list is executed during reconciliation. Native evidence remains required wherever
the preserved state says `EVIDENCE_REQUIRED` or `IMPLEMENTATION_AND_EVIDENCE_REQUIRED`; those labels
are not promoted by static policy. Zombie Lair and Stamina retain their explicit REC-R19 deferral,
Speedup retains REC-P09 deferral, and every other state remains exactly as shown in the table.
Later route work must use existing authority bindings and safety gates; this decision adds no queue,
registry, scheduler, evidence, or runtime state authority.
