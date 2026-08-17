# Daily Quest handler roadmap

Current status lives in `tasks/daily_quest_execution_matrix.json`. This roadmap describes
dependency order and reusable implementation families. It does not authorize runtime work.

## Boundary

Daily Quest only. Main Quest Claim is excluded from active implementation,
registration, scheduler, and prompt scope. One aggregate selected-Daily Claim
flow owns every ordinary Daily Claim tap; milestone Claim remains separate.
Objective flows provide completion attribution only.

All scheduler eligibility is false. Legacy Bliss operator registrations for
Alliance Help, Personal Might Praise, and Personal Might Claim are retired.
Offline modules, SQLite task-state persistence, and one-pulse scheduling
remain dormant infrastructure.

Catalog admission is strict: raw/lossless Bliss frame or derived inventory, positive Quest screen,
positive selected Daily tab, visible objective-list row, non-Main classification, and exact source
path are all required. See `tasks/daily_quest_provenance_audit.json`; prose and synthetic fixtures
cannot admit Daily objectives.

## Dependency order

1. Reconcile retained names into catalog identity, aliases, parameterized variants, and explicit
   evidence conflicts.
2. Freeze catalog/matrix authority split and cross-check all 31 proven objective keys.
3. Validate selected Daily-tab recognition, bounded scroll inventory, row identity, current
   game-day binding, and Main-negative recognition.
4. Keep one aggregate ordinary Daily Claim independent from milestone Claim.
5. Preserve historical Alliance Help and Personal Might Praise evidence while verifying their
   selected-Daily completion-attribution providers remain actionless and unregistered.
6. Review free/evidence-gated contracts: Bioenhancer, Supply Depot, Recruitment, and Nanoweapon.
7. Build shared route and recognizer primitives offline.
8. Build policy-gated families only after product decisions and BlueStacks-native evidence.
9. Keep disabled strategic flows specified, offline-only, unregistered, and scheduler-ineligible.
10. Review dormant persistence/scheduler integration.
11. Pass separate runtime-integration gate before any live state or new registration.

Resource-building output boost is specified by `tasks/resource_boost_disabled.py` as an
offline-only identity/duration/cost/boost-state contract. Its policy remains disabled; no boost
dispatch, registration, live input, or scheduler eligibility is implied.

## Reusable families

### Foundation and support

- Daily inventory/reconciliation: selected-tab source, bounded scroll, overlap, row identity,
  points/reset/game-day evidence, and fail-closed Main-negative.
- Aggregate Daily Claim: one ordinary free non-milestone Claim control on
  selected Daily, one tap, positive points delta, and no remaining ordinary
  Claim controls. Objective and row identity are not authorization inputs.
- Milestone Claim: ready chest/panel-local target, separate from ordinary row Claim.
- Persistence/scheduler: serializable task state, SQLite v2 adapter, one candidate per pulse,
  lease/unresolved global gates; no transport.

### Retired completion providers

- Alliance Help: selected-Daily progress attribution only. Historical Help All and individual Help
  evidence is retained, but there is no active route, target, dispatch, registration, or scheduler
  eligibility.
- Personal Might Praise: selected-Daily progress attribution only. Historical Praise evidence is
  retained, but there is no active route, target, dispatch, registration, or scheduler eligibility.

### Free or evidence-gated

- Bioenhancer: one free Research action; paid/10x branches blocked. The supervised live action is
  confirmed by `bioenhancer-free-1784069057` with zero cost, quantity one, one transport call,
  and a positive result/cooldown postcondition. Daily Claim remains a separate pending boundary:
  the later selected-Daily inspection occurred after the `daily-2026-07-14` reset and showed the
  Bioenhancer row at `0/1`, so no same-day Claim-ready state is asserted.
- Supply Depot: navigation evidence acquired for selected Daily `0/5`, direct Depot route,
  four visible Free controls, one annotated free-single reward target, and bounded Daily return.
  Collection remains policy-gated until game-day binding, known-reward approval, postcondition,
  and Daily reconciliation are proven.
- Recruitment: free single recruitment only; no 10x/premium/unknown confirmation.
- Nanoweapon: Craft Weapon only; Material Production and Inherit are distinct and excluded.

### Material/resource-policy

- Enhancement engine: Gear, Chip, Module parameterized by tab/item/material recognizers;
  one-star material, quantity one, no Auto Select.
- Campaign AP: common AP/campaign result primitives; Sweep/Auto Complete variants; Challenge
  remains separate.
- World/stamina engine: map state, tile search, occupancy, march capacity, stamina, and result
  recognizers. GnBots geometry remains non-authorizing.
- Zombie Lair: level/stamina/march policy and positive participation result.
- Consume Stamina: separate objective using shared primitives; current implementation is
  counter-only and policy-disabled, with no spend transaction.
- Gathering: proven Wood, Steel, and Gas variants with resource-specific target/quantity; offline
  node/march contract complete. Gather Food/Gathered Food remains outside scope until selected-
  Daily evidence qualifies it.
- Training: Fighter, Rider, Shooter, Vehicle variants with shared queue/quantity engine; current
  implementation is counter-only and policy-disabled, with no training transaction.

### Disabled or strategic

- Building Upgrade: proven generic target only; offline identity/level contract complete and
  policy-disabled. Vehicle Depot wording is Main-only evidence.
- Hero Duel: event/Join/progress identity replay complete offline; PvP remains policy-disabled with
  no event-entry path.
- Tech Upgrade: prerequisite/level identity replay complete offline; research remains
  policy-disabled with no upgrade transaction.
- Hero Upgrade: selected-hero/material/level identity replay complete offline; hero upgrade remains
  policy-disabled with no upgrade transaction.
- Hero Upgrade and Hero Ownership: separate semantics.
- Purchases: Box, Ruins Shop, Rare Earth Shop, and Alliance Shop variants share offline
  offer/cost/item replay; purchase remains policy-disabled with no transaction.
- Donation: Alliance Technology target/resource/count replay complete offline; donation remains
  policy-disabled with no transaction.
- Speedups: 180-minute item/timer replay complete offline; item consumption remains
  policy-disabled with no transaction.
- Challenges: Ruins identity/cost/result replay complete offline; entry remains policy-disabled.
  Ultimate wording is Main-only evidence.
- Hero Duel: PvP entry.
- Resource-building boost: any resource building target.
- Zombie Hunt and Headquarters PvP: no Daily owner; retained candidates remain outside catalog and
  matrix pending qualifying selected-Daily evidence.

## Family rules

Shared behavior belongs in one family engine with explicit parameterized variants. Objective text
alone never creates a duplicate handler. Variants may not share ownership when target identity,
consequence, cost, or postcondition differs materially. Every consequential family needs:
current source, exact target, expected successor, cost/resource policy, one transaction boundary,
positive semantic postcondition, bounded recovery, immutable evidence, deterministic replay tests,
and separate Claim authorization.

## Promotion

`OFFLINE_ONLY` → `EVIDENCE_GATED` → `SUPERVISED_VALIDATION` → `LIVE_VALIDATED` →
`AUTOMATIC_ENABLED` is closed. `DISABLED_POLICY` is terminal until explicit policy change.
Promotion requires BlueStacks-native evidence, profile/hash compatibility, positive postconditions,
fresh game-day identity, central policy approval, and no unresolved action. GnBots manifest facts
may guide research but never authorize runtime input. Current Bioenhancer status is split:
`BIOENHANCER_RESEARCH_CONFIRMED` for the single supervised research transaction, with
`BIOENHANCER_DAILY_RECONCILIATION_PENDING` and Claim unperformed. The canonical action result is
`evidence/sessions/20260714-bioenhancer-live-transaction/bioenhancer-free-1784069057-result.json`;
it does not authorize Claim.
