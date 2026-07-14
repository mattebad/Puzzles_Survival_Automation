# Daily Quest handler roadmap

Current status lives in `tasks/daily_quest_execution_matrix.json`. This roadmap describes
dependency order and reusable implementation families. It does not authorize runtime work.

## Boundary

Daily Quest only. Main Quest Claim is excluded from active implementation, registration, scheduler,
and prompt scope. Generic Daily Claim, exact Personal Might Daily Claim, and milestone Claim remain
separate contracts. Objective execution never implies Claim readiness.

All scheduler eligibility is false. Existing `pnsctl` operator registrations remain unchanged:
Alliance Help, Personal Might Praise, and exact Personal Might Daily Claim. Offline modules,
SQLite task-state persistence, and one-pulse scheduling remain dormant infrastructure.

## Dependency order

1. Reconcile retained names into catalog identity, aliases, parameterized variants, and explicit
   evidence conflicts.
2. Freeze catalog/matrix authority split and cross-check all 36 objective keys.
3. Validate selected Daily-tab recognition, bounded scroll inventory, row identity, current
   game-day binding, and Main-negative recognition.
4. Keep generalized row Claim, exact Personal Might Claim, and milestone Claim independent.
5. Preserve and verify existing Alliance Help and Personal Might Praise flows.
6. Review free/evidence-gated contracts: Bioenhancer, Supply Depot, Recruitment, and Nanoweapon.
7. Build shared route and recognizer primitives offline.
8. Build policy-gated families only after product decisions and Bliss-native evidence.
9. Keep disabled strategic flows specified, offline-only, unregistered, and scheduler-ineligible.
10. Review dormant persistence/scheduler integration.
11. Pass separate runtime-integration gate before any live state or new registration.

## Reusable families

### Foundation and support

- Daily inventory/reconciliation: selected-tab source, bounded scroll, overlap, row identity,
  points/reset/game-day evidence, and fail-closed Main-negative.
- Generalized Daily Claim: exact completed ordinary row-local Claim, zero-cost proof, same-row
  positive postcondition.
- Personal Might Claim: exact validated row-specific support flow, separate from Praise.
- Milestone Claim: ready chest/panel-local target, separate from ordinary row Claim.
- Persistence/scheduler: serializable task state, SQLite v2 adapter, one candidate per pulse,
  lease/unresolved global gates; no transport.

### Existing validated flows

- Alliance Help: one parameterized action family with preferred Help All and individual Help
  fallback. Canonical route `daily_go_to_speedup_help`.
- Personal Might Praise: named navigation route, current-frame rank-one target, cooldown/day
  bound, one dispatch, positive control/postcondition.

### Free or evidence-gated

- Bioenhancer: one free Research action; paid/10x branches blocked.
- Supply Depot: free known non-premium collection until Free disappears.
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
- Consume Stamina: separate objective using shared primitives.
- Gathering: Food, Wood, Steel, Gas variants with resource-specific target/quantity. Gather Food
  provenance covers both `Gather Food` and `Gathered Food`.
- Training: Fighter, Rider, Shooter, Vehicle variants with shared queue/quantity engine.

### Disabled or strategic

- Building Upgrade: generic and Vehicle Depot target variants.
- Tech Upgrade: Research target variant.
- Hero Upgrade and Hero Ownership: separate semantics.
- Purchases: Box, Ruins Shop, Rare Earth Shop, Alliance Shop variants through one allowlist engine.
- Donation: Alliance Tech resource policy.
- Speedups: item/timer allowlist.
- Challenges: Ruins and Ultimate variants remain distinct.
- Hero Duel: PvP entry.
- Resource-building boost: any resource building target.
- Zombie Hunt: level-5 ×3 distinct from Zombie Lair.
- Headquarters PvP: attack/win remains disabled.

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
Promotion requires Bliss-native evidence, profile/hash compatibility, positive postconditions,
fresh game-day identity, central policy approval, and no unresolved action. GnBots manifest facts
may guide research but never authorize runtime input.
