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

## Daily Quest Portfolio reconciliation — 2026-08-16

This checkpoint reconciles planning authority only. It implements no gameplay behavior, selects no
queue flow, freezes no execution manifest, authorizes no runtime input, and changes no registration,
scheduler, composition, M6, or Bliss state.

Authority is singular by concern:

- `tasks/daily_quest_catalog.json` owns admitted Daily objective identity. Only current
  selected-Daily native objective-list evidence may add an objective.
- `tasks/daily_quest_execution_matrix.json#portfolio_reconciliation` owns current portfolio
  objective owner/state, evidence gaps, and dependency order. The older per-objective rows remain
  capability snapshots and may describe stale disabled implementations.
- `tasks/flow_delivery_queue.json#portfolio_staging` mirrors execution order and blockers without
  participating in queue selection. `active_flow_id` remains `null`.
- `BACKLOG.md` retains implementation and evidence history. Its older "policy required" statements
  do not override product policy explicitly closed by this portfolio checkpoint.

### Historical 32-row reconciliation

The four historical portrait iOS screenshots `IMG_5076.PNG` through `IMG_5079.PNG` contain 32 visible
Daily rows. They are design references, not current-runtime authorization.

- `use_resource_item` is visible historically but remains `ADMISSION_EVIDENCE_REQUIRED`; no catalog
  or execution-matrix objective may be created until a current selected-Daily native frame proves
  the exact row.
- `gather_food` is visible historically but remains excluded from Daily catalog ownership because
  the current audit has only synthetic evidence. Food may later serve as the separately bounded
  gathering proving slice without implying a Daily objective.
- Ultimate Challenge is visible historically but remains excluded under the current native
  Main-objective reclassification.
- `upgrade_tech` and `buy_box` are absent from the four historical screenshots but remain admitted
  because the newer current selected-Daily native inventory proves them.

### Accepted foundations preserved

- Delegated Luna receipt enforcement, dry-run proof, and zero-input ownership observation are
  accepted and must not be rebuilt.
- Enhancement BlueStacks implementation and verifier repair are accepted offline. Gear, Chip, and
  Module native semantics/canaries remain three separate evidence tasks.
- The HUD-only Home → World → Search → Back → Home boundary is accepted. It grants no atlas, node,
  resource, occupancy, formation, march, stamina, AP, or combat authority.
- Research Lab Nova Praise, selected-Daily Personal Might Praise, Personal Might Claim,
  Bioenhancer free research, Help Allies, Recruitment, Training, Campaign AP, and Ruins Challenge
  retain their accepted proof layers. Their existing production-registration snapshots are not
  broadened, and scheduler eligibility remains false.
- Supply Depot canonical route and free-attempt mechanics are reusable, but Daily all-free-attempt
  completion through `Free` disappearance and independent Daily `5/5` proof remain missing.

### Scoped owner and state decisions

- `daily-row-claim` owns generalized ordinary row Claim: `EVIDENCE_REQUIRED`.
- `daily-milestone-claim` owns milestone chest Claim: `EVIDENCE_REQUIRED`.
- `use-resource-item` owns the historical candidate: `ADMISSION_EVIDENCE_REQUIRED`.
- `supply-depot` owns Daily all-free collection: `EVIDENCE_REQUIRED`.
- `alliance-tech-donation` owns ten yellow-resource donations: `IMPLEMENTATION_AND_EVIDENCE_REQUIRED`.
- `alliance-shop-purchase`, `ruins-shop-purchase`, and `rare-earth-shop-purchase` independently own
  their shop identities and counters: `IMPLEMENTATION_AND_EVIDENCE_REQUIRED`.
- `nano-material-maintenance` owns six-hour Material Production:
  `IMPLEMENTATION_AND_EVIDENCE_REQUIRED`.
- `nanoweapon-daily` owns claim-first 100-part Normal Craft:
  `IMPLEMENTATION_AND_EVIDENCE_REQUIRED`.
- `hero-upgrade` owns Wally-only three-upgrade/reset behavior:
  `IMPLEMENTATION_AND_EVIDENCE_REQUIRED`.
- `hero-duel` owns three free launches and immediate exits:
  `IMPLEMENTATION_AND_EVIDENCE_REQUIRED`.
- `enhancement-gear-native-proof`, `enhancement-chip-native-proof`, and
  `enhancement-module-native-proof` independently own their canaries: `EVIDENCE_REQUIRED`.
- `gathering-search-level5`, `gathering-gas-reveal`, `gathering-free-tile-binding`,
  `gathering-march-dispatch`, and `gathering-variant-canaries` own the five ordered gathering gates:
  `IMPLEMENTATION_AND_EVIDENCE_REQUIRED`. Passing one gate grants no later authority.

The portfolio supplies product decisions for every scoped owner above. Old disabled replay
contracts identify missing implementation, not an unresolved user decision. The Gathering
product-policy registry and executable queue row now agree on the exact level-5/free-tile/free-slot/
default-formation policy and remain evidence-gated. Rare Earth Shop still requires the exact
current item label/cost as evidence; `use_resource_item` still requires catalog admission.

### Evidence and dependency order

Execute no item from this list during reconciliation. The next architecture task freezes only one
manifest for the first queue-authorized item.

1. Daily row Claim: current ready row-local Claim and row disappearance or point delta.
2. Daily milestone Claim: separate ready chest and opened-chest or point successor.
3. Use Resource Item: current catalog admission, then exact `1K Food`, quantity one, inventory/Daily
   successor, and Home.
4. Supply Depot: all displayed free attempts through `Free` disappearance and Daily `5/5`.
5. Alliance Tech: highlighted tech, yellow-resource control, diamond negative, ten-count/resource
   deltas, and Home.
6. Alliance Shop, Ruins Shop, Rare Earth Shop: independent item/cost/balance/successor evidence;
   shared navigation does not merge ownership.
7. Nano Material Production: claim/idle/active/start/21600-second timer, due-time restart
   persistence, and Home.
8. Nanoweapon Daily: only after Nano Material acceptance; completed-claim, Normal Craft, 100 parts,
   43200-second timer, reset idempotency, Daily `0→1`, and Home.
9. Hero Upgrade, then Hero Duel: Wally/reset/reorder evidence; then free-opponent/popup/exit/loss
   variants and three combat-dispatch receipts.
10. Gear, Chip, and Module: separate fresh native semantics and canaries.
11. Gathering: accepted World boundary → category/level 5 → Gas reveal → free-tile/occupancy
    binding → one free-slot/default-formation Food proving march → independent Wood/Steel/Gas
    canaries.

### Explicit deferrals

- Both Zombie Lair items remain deferred.
- Speedup 180 minutes and Rare Earth Pit income remain later backlog items.
- Unscoped admitted objectives retain the explicit owner/state recorded in
  `portfolio_reconciliation.catalog_objective_ownership`; none is silently promoted.

