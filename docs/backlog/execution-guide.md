# Recovery execution guide

This guide indexes the 74 inactive recovery tickets. It describes how to read and bound future
planning work; it is not a queue, registry, scheduler, conductor, evidence authority, or runtime
control plane. The root [`BACKLOG.md`](../../BACKLOG.md) is a small index. The four linked ticket
files below are the current planning records, and the original 148-record backlog is preserved at
[`docs/archive/backlog-legacy.md`](../archive/backlog-legacy.md).

## Before a future assignment

1. Read this guide, the complete ticket body, and the common
   [`planning conventions`](../backlog-task-contract.md).
2. Confirm named dependencies, product decisions, exact source/test paths, and integration-hunk
   overlap. A ticket's `READY` status is only an offline planning signal; it does not start work.
3. Use the ticket's Scope, Changes, Non-goals, Acceptance, Verification, Native gate, Integration
   owner, PR boundary, Rollback, Runtime authorization, and Completion fields as the contract. Do
   not reconstruct a ticket from a queue packet, derived index, status projection, receipt, Git
   fingerprint, or historical record.
4. Keep one focused PR boundary per ticket (or the documentary/operational record named by the
   ticket). Shared callers and schema/registry/service seams must be cut over in the same PR; “wire
   later” is not completion.
5. Offline work uses fake/replay adapters and isolated temporary state with zero transport. Native
   work is a separate supervised gate with an explicit current record, budget, owner, and rollback.
   BlueStacks development evidence is not NAS/Unraid production acceptance.

No planning record authorizes a branch, worktree, commit, PR, host/device/ADB/VM operation, native
observation, evidence mutation, scheduler enablement, registration, or production state mutation.
Unknown or unresolved consequential outcomes remain retained for reconciliation or blocked and are
never automatically retried.

## Direct ticket index

Links point directly to each stable ticket heading. All 74 records are listed exactly once.

### Foundation (REC-F01–REC-F17)

- [`REC-F01` — Fail-closed screen ambiguity and immutable capture provenance](foundation.md#rec-f01--fail-closed-screen-ambiguity-and-immutable-capture-provenance)
- [`REC-F02` — Enforce bounded, terminating ROI OCR workers](foundation.md#rec-f02--enforce-bounded-terminating-roi-ocr-workers)
- [`REC-F03` — Reject unknown or contradictory overlay successors](foundation.md#rec-f03--reject-unknown-or-contradictory-overlay-successors)
- [`REC-F04` — Release only the exact newly acquired lease on denied claim](foundation.md#rec-f04--release-only-the-exact-newly-acquired-lease-on-denied-claim)
- [`REC-F05` — Keep public shadow scheduling initialization-free and mutation-free](foundation.md#rec-f05--keep-public-shadow-scheduling-initialization-free-and-mutation-free)
- [`REC-F06` — Prevent selection-only handlers from consuming gameplay occurrences](foundation.md#rec-f06--prevent-selection-only-handlers-from-consuming-gameplay-occurrences)
- [`REC-F07` — Persist bounded repeats, occurrence ordinals, retry backoff, and exhaustion blocks](foundation.md#rec-f07--persist-bounded-repeats-occurrence-ordinals-retry-backoff-and-exhaustion-blocks)
- [`REC-F08` — Make evidence filenames portable and action counts truthful](foundation.md#rec-f08--make-evidence-filenames-portable-and-action-counts-truthful)
- [`REC-F09` — Establish the canonical static registry, SQLite schema, and attachable run session](foundation.md#rec-f09--establish-the-canonical-static-registry-sqlite-schema-and-attachable-run-session)
- [`REC-F10` — Retain one guarded canonical native transport adapter](foundation.md#rec-f10--retain-one-guarded-canonical-native-transport-adapter)
- [`REC-F11` — Compose shared Home-ready, Atlas, Back, startup, and VIP ownership](foundation.md#rec-f11--compose-shared-home-ready-atlas-back-startup-and-vip-ownership)
- [`REC-F12` — Restore Home Atlas localization offline without Campaign retry](foundation.md#rec-f12--restore-home-atlas-localization-offline-without-campaign-retry)
- [`REC-F13` — Cut World over exclusively to one canonical runner](foundation.md#rec-f13--cut-world-over-exclusively-to-one-canonical-runner)
- [`REC-F14` — Run real pulses with due/retry/heartbeat/fairness/shutdown semantics](foundation.md#rec-f14--run-real-pulses-with-dueretryheartbeatfairnessshutdown-semantics)
- [`REC-F15` — Expose coherent CLI controls and real lease health](foundation.md#rec-f15--expose-coherent-cli-controls-and-real-lease-health)
- [`REC-F16` — Provide the canonical concurrency/crash/reset/fairness acceptance package](foundation.md#rec-f16--provide-the-canonical-concurrencycrashresetfairness-acceptance-package)
- [`REC-F17` — Adopt remaining direct OCR callers behind the bounded engine](foundation.md#rec-f17--adopt-remaining-direct-ocr-callers-behind-the-bounded-engine)

### Daily (REC-D01–REC-D12)

- [`REC-D01` — Reconcile current Daily catalog identity and no-premium policy](daily.md#rec-d01--reconcile-current-daily-catalog-identity-and-no-premium-policy)
- [`REC-D02` — Provide the canonical selected-Daily inventory and reset fact](daily.md#rec-d02--provide-the-canonical-selected-daily-inventory-and-reset-fact)
- [`REC-D03` — Cut ordinary Daily Claim over to one aggregate owner](daily.md#rec-d03--cut-ordinary-daily-claim-over-to-one-aggregate-owner)
- [`REC-D04` — Add the separate ready milestone chest controller](daily.md#rec-d04--add-the-separate-ready-milestone-chest-controller)
- [`REC-D05` — Migrate Ultimate Daily Join to the zero-resource Flee route](daily.md#rec-d05--migrate-ultimate-daily-join-to-the-zero-resource-flee-route)
- [`REC-D06` — Migrate Bioenhancer to one free Research action](daily.md#rec-d06--migrate-bioenhancer-to-one-free-research-action)
- [`REC-D07` — Unify Daily recruitment and three-tier maintenance](daily.md#rec-d07--unify-daily-recruitment-and-three-tier-maintenance)
- [`REC-D08` — Implement native Alliance Help for ten free requests](daily.md#rec-d08--implement-native-alliance-help-for-ten-free-requests)
- [`REC-D09` — Implement Personal Might Praise separately from Nova](daily.md#rec-d09--implement-personal-might-praise-separately-from-nova)
- [`REC-D10` — Exhaust only free Supply Depot collections and reconcile Daily progress](daily.md#rec-d10--exhaust-only-free-supply-depot-collections-and-reconcile-daily-progress)
- [`REC-D11` — Canonicalize Nova to one free Praise pulse](daily.md#rec-d11--canonicalize-nova-to-one-free-praise-pulse)
- [`REC-D12` — Orchestrate a useful Daily routine with observed milestone acceptance](daily.md#rec-d12--orchestrate-a-useful-daily-routine-with-observed-milestone-acceptance)

### Resources and policy (REC-R01–REC-R19, REC-P01–REC-P12)

- [`REC-R01` — Preserve ResourceEffectAuthority parity at the canonical action boundary](resources.md#rec-r01--preserve-resourceeffectauthority-parity-at-the-canonical-action-boundary)
- [`REC-R02` — Use exactly one 1K Food item without Daily inheritance](resources.md#rec-r02--use-exactly-one-1k-food-item-without-daily-inheritance)
- [`REC-R03` — Gear one-star single-material enhancement](resources.md#rec-r03--gear-one-star-single-material-enhancement)
- [`REC-R04` — Chip one-star single-material enhancement](resources.md#rec-r04--chip-one-star-single-material-enhancement)
- [`REC-R05` — Module one-star single-material enhancement](resources.md#rec-r05--module-one-star-single-material-enhancement)
- [`REC-R06` — Fighter T8 current-maximum training with approved boxes](resources.md#rec-r06--fighter-t8-current-maximum-training-with-approved-boxes)
- [`REC-R07` — Rider T1 once-daily 250 training without boxes](resources.md#rec-r07--rider-t1-once-daily-250-training-without-boxes)
- [`REC-R08` — Shooter T8 once-daily 250 training without boxes](resources.md#rec-r08--shooter-t8-once-daily-250-training-without-boxes)
- [`REC-R09` — Vehicle T1 current-maximum training with approved boxes](resources.md#rec-r09--vehicle-t1-current-maximum-training-with-approved-boxes)
- [`REC-R10` — Campaign destination navigation without AP execution](resources.md#rec-r10--campaign-destination-navigation-without-ap-execution)
- [`REC-R11` — Campaign AP Auto Battle at exact configured destinations](resources.md#rec-r11--campaign-ap-auto-battle-at-exact-configured-destinations)
- [`REC-R12` — Ruins zero-cost NPC challenge](resources.md#rec-r12--ruins-zero-cost-npc-challenge)
- [`REC-R13` — Ruins per-category chest maintenance and durable continuation](resources.md#rec-r13--ruins-per-category-chest-maintenance-and-durable-continuation)
- [`REC-R14` — Nano Material Production six-hour maintenance](resources.md#rec-r14--nano-material-production-six-hour-maintenance)
- [`REC-R15` — Nanoweapon Normal Craft one start per reset](resources.md#rec-r15--nanoweapon-normal-craft-one-start-per-reset)
- [`REC-R16` — Shared direct Home-to-World gathering/march controller](resources.md#rec-r16--shared-direct-home-to-world-gatheringmarch-controller)
- [`REC-R17` — Wood 30000 and Steel 6000 gathering variants](resources.md#rec-r17--wood-30000-and-steel-6000-gathering-variants)
- [`REC-R18` — Gas 1500 gathering with bounded reveal/rebind](resources.md#rec-r18--gas-1500-gathering-with-bounded-revealrebind)
- [`REC-R19` — Defer Zombie Lair maintenance and Daily attribution pending product decision](resources.md#rec-r19--defer-zombie-lair-maintenance-and-daily-attribution-pending-product-decision)
- [`REC-P01` — Decide Ruins Shop purchase policy](resources.md#rec-p01--decide-ruins-shop-purchase-policy)
- [`REC-P02` — Decide Rare Earth Shop purchase policy](resources.md#rec-p02--decide-rare-earth-shop-purchase-policy)
- [`REC-P03` — Decide Alliance Shop purchase policy](resources.md#rec-p03--decide-alliance-shop-purchase-policy)
- [`REC-P04` — Resolve Hero Upgrade identity and no-diamond policy](resources.md#rec-p04--resolve-hero-upgrade-identity-and-no-diamond-policy)
- [`REC-P05` — Decide Hero Duel participation policy](resources.md#rec-p05--decide-hero-duel-participation-policy)
- [`REC-P06` — Decide Building Upgrade target/resource/queue policy](resources.md#rec-p06--decide-building-upgrade-targetresourcequeue-policy)
- [`REC-P07` — Decide Tech Upgrade target/resource/queue policy](resources.md#rec-p07--decide-tech-upgrade-targetresourcequeue-policy)
- [`REC-P08` — Decide Alliance Tech Donation 10 target/resource policy](resources.md#rec-p08--decide-alliance-tech-donation-10-targetresource-policy)
- [`REC-P09` — Decide 180-minute Speedup policy](resources.md#rec-p09--decide-180-minute-speedup-policy)
- [`REC-P10` — Decide Resource Building Boost policy](resources.md#rec-p10--decide-resource-building-boost-policy)
- [`REC-P11` — Defer Rare Earth Pit income discovery and policy](resources.md#rec-p11--defer-rare-earth-pit-income-discovery-and-policy)
- [`REC-P12` — Decide Resource Buy Box policy separately from Boost](resources.md#rec-p12--decide-resource-buy-box-policy-separately-from-boost)

### Operations (REC-O01–REC-O14)

- [`REC-O01` — Coordinate cleanup PR and reconcile legacy backlog](operations.md#rec-o01--coordinate-cleanup-pr-and-reconcile-legacy-backlog)
- [`REC-O02` — Accept final NAS-only runtime and production adapter profile](operations.md#rec-o02--accept-final-nas-only-runtime-and-production-adapter-profile)
- [`REC-O03` — Enforce expected account and server session guard](operations.md#rec-o03--enforce-expected-account-and-server-session-guard)
- [`REC-O04` — Implement safe manual takeover with fenced pause and reconcile](operations.md#rec-o04--implement-safe-manual-takeover-with-fenced-pause-and-reconcile)
- [`REC-O05` — Package the private NAS-local worker and resource boundaries](operations.md#rec-o05--package-the-private-nas-local-worker-and-resource-boundaries)
- [`REC-O06` — Verify backup/restore and bounded VM-worker lifecycle](operations.md#rec-o06--verify-backuprestore-and-bounded-vm-worker-lifecycle)
- [`REC-O07` — Operate bounded monitoring, evidence retention, and health recovery](operations.md#rec-o07--operate-bounded-monitoring-evidence-retention-and-health-recovery)
- [`REC-O08` — Supervise current native World acceptance by scenario](operations.md#rec-o08--supervise-current-native-world-acceptance-by-scenario)
- [`REC-O09` — Pilot the hosted service for 24 hours then 72 hours](operations.md#rec-o09--pilot-the-hosted-service-for-24-hours-then-72-hours)
- [`REC-O10` — Maintain route-specific current-native acceptance ledger](operations.md#rec-o10--maintain-route-specific-current-native-acceptance-ledger)
- [`REC-O11` — Run progressive seven-day and 21-day NAS-only closure](operations.md#rec-o11--run-progressive-seven-day-and-21-day-nas-only-closure)
- [`REC-O12` — Retire delivery receipts and legacy runtime authority after cutover](operations.md#rec-o12--retire-delivery-receipts-and-legacy-runtime-authority-after-cutover)
- [`REC-O13` — Retire duplicate registries, scheduler branches, and ledgers](operations.md#rec-o13--retire-duplicate-registries-scheduler-branches-and-ledgers)
- [`REC-O14` — Retire duplicate Home, Back, popup, perception, and accounting wrappers](operations.md#rec-o14--retire-duplicate-home-back-popup-perception-and-accounting-wrappers)

## Safety and completion boundaries

The canonical runtime remains the existing `automation_service` SQLite state manager, fenced service
lease, flow/run generations, action reservations, and two persisted gates. Static route facts only
seed missing rows disabled. `ResourceEffectAuthority` remains authoritative for effectful routes
until its canonical parity is proven. Runtime launchers and controls, manual-only states, and live
safety gates are not simplified by these planning records.

The plan distinguishes four outcomes: offline code merged, current native evidence accepted,
scheduler accepted, and explicitly enabled. Only the existing runtime authorities may perform the
last transition. A plan link, queue/index entry, historical evidence record, or passing offline test
cannot substitute for it.
