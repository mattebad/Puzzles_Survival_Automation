# Automation service

`automation_service/` is the canonical local runtime composition package, with offline adapters
and explicitly authorized BlueStacks execution. It reuses the existing
`safe_action_core` policy, executor, store, action lifecycle, and
`SQLiteSchedulerInvocationRepository`; `tasks.scheduler_task_result` supplies normalized
scheduler-aware results, while `tasks.perception_bundle`, native-frame replay, and existing
Campaign/Home semantics remain the source contracts.

Current dated route acceptance and source limits are in the
[November 2 status report](bluestacks-route-status-20261102.md). The two-hour serial
cadence is scoped to `3c222af`. After the Astra corrections, `cfe449c` passed a fresh
uninterrupted Gear/Chip/Module family: one Profile visit, 23 inputs, three Confirms
and Home, each stock minus one and EXP100 to110. Its independent audit also checks
atomic progress and the shared Home path. Broader route/cadence receipts keep their
earlier source scopes; accepted daily routes are not forced to repeat for coverage.

## Boundaries

- Context classification is read-only. Flow handlers own action semantics.
- The service scheduler uses UTC epoch `next_eligible_at` values. It does not
  compose two schedulers.
- Fake and replay adapters have zero transport.
- The BlueStacks adapter is supervised-only, requires a flow-bound single-use admission token,
  and can dispatch only through `SafeActionExecutor` with a bound core request/capability. The
  service CLI has no arbitrary ADB, coordinate, shell, tap, remote, or automatic endpoint.
- The legacy production registry remains disabled in
  `tasks/flow_delivery_disabled_production_registry.json`; it records the disabled
  `NOT_REGISTERED` posture and is separate from canonical service admission. The canonical code
  registry has twenty-three fixed flow specs, which report `REGISTERED`; this is composition only.
  SQLite service/flow enablement is separate, defaults off, and is restored off after bounded tests.
- Campaign selection remains non-consuming. Explicit native service composition installs
  the Campaign runner behind canonical claims and dispatch fences, reusing destination policy,
  Atlas navigation, and `tasks.campaign_auto_battle` contracts. It spends affordable AP through
  verified battles, then returns Home and waits 300 seconds after the whole drain. Sweep,
  Blitz, Auto Complete, and AP refill remain excluded.
- Retention operations classify records only; deletion remains in the dedicated evidence workflow.
- Canonical capture cycles snapshot payload and metadata before hashing. Typed observations
  must bind the requested session, capture ordinal, dimensions, timestamp, and payload,
  transport, and semantic digests; a cached or hash-only result cannot gain that binding.
- Conflicting screen, overlay, or target matches fail closed. Pre-transport target rebinding
  requires a newer capture ordinal, non-regressing capture time, current age within the existing
  temporal policy, and matching source/target stable ROIs. Equal clock ticks are permitted
  because fresh capture ordinals distinguish events on coarse-resolution clocks.
- Actual OCR requires one `CropRoiRequest` carrying capture identity, ROI, mode, and an
  explicit real-monotonic deadline. The padded raw ROI is capped at 262144 pixels;
  full-frame and out-of-bounds crops are rejected. Crop-only validation needs no OCR deadline.
- For capture-bound semantic OCR, `run_semantic_ocr` owns the process boundary. Windows Job Objects and Linux
  process groups contain helpers; success and timeout both drain the tree and reap its root.
  A 250ms cleanup reserve is deducted from the execution budget. Timeout is `UNKNOWN/OCR_DEADLINE`.
- `ScreenDefinition.ocr` is a spawn-picklable `(pixels, psm) -> str` engine;
  `ocr_request` supplies the fixed request or a capture/deadline factory.
  `ocr_recognizer` is pure interpretation of the completed OCR observation and current capture,
  not another OCR callback. Existing provenance normalization still applies.
- Existing capture-bound Supply Depot calls never repair identity or fall back after denial.
  Other native readers retain their route-specific boundaries. Enhancement uses the
  existing Tesseract subprocess timeout: at most five seconds per call within a shared
  fifteen-second recognition budget, checking the owning runtime checkpoint between
  calls. A timeout yields unrecognized `OCR_DEADLINE`, never confirmation or a repeated
  resource dispatch. This does not claim the semantic OCR worker's process-tree containment.
  Mutable Enhancement family progress is flushed to a sibling temporary file and
  atomically replaced, preserving the last complete document on an interrupted write.
- Full-frame animation variance is not a source/target change when authoritative stable ROIs
  still match. Unsupported mutable payload types fail closed rather than losing shape or type.
- Denied sessions preserve borrowed service leases. Fresh admission leases are released
  only by their exact owner/process/generation fence, including after claim rollback.
  Run-associated release also checks the run token atomically, so a retried or different
  active run cannot lose ownership to an older session's cleanup.
- `reset_bounded` requires a canonical ready-batch ID and revision. The first persisted
  limit governs the entire reset; later batches do not receive another allowance.
  Ordinals, batch identity, timer anchors, and retry identity survive restart.
- Batch/revision changes require a persisted successful predecessor plus changed-UI
  and reconciliation facts. Failed or unresolved predecessors cannot authorize advancement.
  Retired batch IDs and retired revisions cannot be replayed; the current pair may consume
  its remaining ordinals. Capture hashes and rescans are not batch authority.
- Retries retain occurrence identity and use a nonzero UTC backoff (at least two seconds).
  Durable exhaustion reports `RESET_BOUNDED_EXHAUSTED` or `RETRY_EXHAUSTED`;
  UTC rollback blocks claims. Reset-scoped routes cannot consume a new reset from an old claim.
  Campaign AP regeneration is not reset-scoped: its active drain retains the claimed identity
  across UTC midnight, with ownership, lease and dispatch fences preserved. That boundary has
  offline proof and actual continuous-client acceptance: three stage entries before
  November 2 00 UTC and five after, eight wins/112 AP/Home. The November 2 report
  records the critical-path comparison at its historical revision. Later shared OCR
  time limits and Enhancement changes are separately scoped; this is not a new
  whole-head midnight or two-hour rerun.

## Canonical `pnsctl` serve facade

The supported live boundary is `scripts/pnsctl.py automation-service`. The thin facade forwards
the remaining arguments unchanged to `automation_service.cli.main`. It validates the standard
supervised mode, BlueStacks adapter, and canonical state path
before serving, and it does not auto-enable, unblock, register, schedule, deploy, or bypass any
existing control gate. The other `pnsctl automation-service` subcommands (`status`, `health`,
`enable`, `disable`, `service-enable`, `service-disable`, `emergency-stop`, `run`, `pulse`) and their
safety notes are listed in the [operations runbook](pns-operations-runbook.md).

Import direction: `scripts/pnsctl.py` imports `automation_service`, never the reverse. The fixed
BlueStacks runtime constants and the fixed-slot binding derivation live in
`tasks/runtime_identity.py`. Native serve receives its owner-bound application startup as the
`application_startup` argument of `automation_service.cli.main`, which `pnsctl` supplies.
`tests/test_architecture_imports.py` enforces zero `automation_service -> scripts.pnsctl` imports
and ratchets the remaining `automation_service -> scripts` module edges.

The normal Campaign launch shape is:

```text
python scripts/pnsctl.py automation-service --mode supervised --adapter bluestacks --state-path .local-orchestrator/bot-state.sqlite3 serve --live --flow campaign --campaign-stage 1-15-9 --campaign-cadence-seconds 300 --adb "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" --serial emulator-5554 --account-id primary-account --server-id primary-server --output-directory .local-captures/automation-service-live
```

Repeat `--flow` for other named routes; the README gives the complete 23-route command. Argument order does not
choose scheduler order; due eligibility and existing controls do. The disabled-gates canonical CLI
proof produced zero captures and zero new runs, so it is control evidence only and does not promote
native route acceptance. Facade checks, the ordinary one-battle live-entrypoint retirement, and
the scheduler/facade consumer checks are recorded separately; their counts are not additive.

The fixed native composition binds 23 canonical routes: Nova, Recruitment, Campaign,
Bioenhancer, Supply, Ultimate, Enhancement, Personal Might, Daily Rewards, Resource Item,
Ruins, Alliance Help, Alliance Donation, Alliance Shop, Daily Shops, Nano Material Production,
Nanoweapon, Hero Duel, Recommended Research, Food Farm Boost, Hall of War, Troop Training,
and Wali Upgrade. The 24th fixed flow spec is `world_map_navigation`, which is selection-only
and has no `serve --flow`.
The ordinary registered selectors remain non-consuming; passing `--flow` alone does not enable a route.

Conditional #74 uses `serve --flow wali-upgrade` through the same supported `pnsctl`
boundary, fixed native composition and canonical SQLite action journal. Only three confirmed
single normal Wali upgrades consume the reset quota; a standard evolution's automatic level
does not. Costs, balances, selected hero and displayed cap are read afresh. A named manual-use
toast is retained as usage evidence with its own frame, not invented as a numeric inventory
decrement; the settled cap/level and exact Antiserum debit are independently required.
Normal Upgrade's separate bulk row is recognized, never pressed. At most one non-spending
Back per pending single action reveals details or the recognized roster plus current Wali
reselection; an unknown dismissal stops without another Back or spending input. Physical
navigation accounting is separate from confirmed normal actions. The full current quote is
bound through the capability's action ID, without changing the reset/ordinal action key.
Actual native binding/SDK/runtime/Core/temp-SQLite replay verified three singles across
evolution, current per-level quotes, partial shortage/resume and durable unknown/no retry.
Historical desktop-derived pixels recognize the bulk row and settled Wali detail quote;
compressed historical evolution-preview quotes remain incomplete and fail closed. Neither
those images nor synthetic execution establish current native acceptance.
Insufficient materials defer, confirmed prefixes persist, and unknown effects forbid identical
retry. Product approval is not runtime enablement. The Campaign block and final 150-diamond
Reset confirmation are unverified, so no Reset input is admitted. Original manual investigation
is not a completed native acceptance run; permanent controls remain disabled.

B adds Ruins/Help; C adds Donation, Alliance Shop and Daily Shops. These are implemented and
offline-proven, not newly live-accepted; production and SQLite runtime controls remain disabled.
Donations count actual successful HOT-tech donations, not ranking points. Alliance Shop requires
one affordable allowlisted Weekly offer or the exact one-star Other fallback, quantity one total.
Daily Shops bounds each approved three-star Chip/Module tab purchase by observed stock and
affordability, with paired item/currency effects. No purchase-effect native acceptance is claimed.
Available HOT donation attempts remain usable while the recharge countdown changes. Shop results
preserve known confirmed progress without converting it to UNKNOWN or permitting duplicate spend.
Daily Shops stays in one visit across both tabs and returns Home once after evaluating both.
Each inner Buy requires freshly paired currency and item-ownership evidence plus numeric
quantity/total verification. Missing item-effect evidence defers that tab before Buy while the
other tab remains independently eligible. Real-journal replay proves confirmed purchases survive
restart without another spend; native purchase-effect acceptance remains `evidence_required`.


Batch D adds canonical-only Nano Material Production and Nanoweapon; no operator rows are added,
and the existing twelve operator routes remain. Production is a zero-resource, single-slot
21,600-second timer across game-day boundaries. Nanoweapon uses separately authorized production
maintenance in the same visit before at most one Normal Craft start/reset: 100 Nano Parts,
43,200 seconds. Exclusive Craft, Daily/D02 ownership and points attribution remain prohibited.
Registration is composition only; production registration and SQLite runtime controls stay disabled.

Batch E adds canonical-only Hero Duel, Recommended Research, and Food Farm Boost routes with fixed
native bindings and no legacy operator rows; the existing twelve operator routes remain unchanged.
All three are explicitly product-approved, but code composition is not production registration or
runtime enablement. Their runtime controls remain off and current live acceptance is
`evidence_required`. Hero Duel investigation recorded five eligible defense heroes and one free
entry/Flee/loss/result cycle, not the required three reset-scoped cycles and lineup/battle acceptance.
Research binds the mapped Home Atlas Research dome from fresh localization. If HUD obscures the
target, safely pan/rebind or defer; never tap through the HUD. The idle first recommendation was
inspected, but no research start or timer was verified. Farm accounts for incidental multi-building
collection effects and prefers an exact owned-item boost. A diamond alternative requires exact
observed zero inventory, an exact current offer within the approved price ceiling, and confirmation/
effect proof; unknown inventory is not zero. One owned-item boost and positive timer were observed;
total inventory and the exact premium branch remain unproven. None of this raw investigation is
route-level live acceptance.

Batch F adds canonical-only Hall of War and Troop Training native service routes. It removes the
legacy Troop Training operator runner/validator/aliases, leaving eleven operator routes, and keeps
supported manual-only `pnsctl bluestacks recover-home`; no compatibility route or standalone
Commander flow is added. The shared Commander preset helper requires a fresh exact `Applied`
observation on every use; cached readiness is not proof, and an already-applied preset is not
switched again. Hall's manual #96 investigation observed one dispatch, reconciled result, and
separate Daily Reward row claim; this is not canonical route acceptance, and unexplained same-reset
manual dispatch blocks an identical retry. Known unavailable-challenge/reward outcomes preserve
confirmed progress and use a bounded 300-second policy re-observation, clipped to the UTC reset;
this is not an observed game cooldown or an unknown-effect retry.
The fixed native factory validates canonical requests through the shared native boundary; Hall
result validation remains in its canonical adapter. A device-free actual held-lock/request probe
passes before device open. This startup proof does not establish live gameplay acceptance.
Training remains `evidence_required`: Fighter T8/current
numeric maximum/continuous and Vehicle T1/current numeric maximum/continuous; Shooter T8/250 and
Rider T1/250 once per reset. Verify exact current costs, before/after balances, current queue and
positive timer; keep current maxima dynamic rather than pinning old amounts. Fighter/Vehicle box
continuations require exact current inventory and effect authority; absent proof they remain
`evidence_required`, with no box dispatch, no expected-warehouse assumption, and no blind Train.
Shooter/Rider never use boxes. No Train Now, premium, speedup, or Daily/D02/points prerequisite.
Both routes are registered in the canonical service but remain production-unregistered,
unscheduled and runtime-disabled; no live route acceptance is claimed.

Daily performs at most one current aggregate Claim, then separately claims glowing chests with
same-slot `Claimed` and canonical journal confirmation. Restart-stable reset/slot keys protect
effects; UNKNOWN stops without identical retry, and already-claimed manual work is skipped.
Complete zero-ready scans return to verified Home. The owner-authorized November 7 #54 observation
was exactly one manual chest tap at zero spend; `glowing` to `Claimed` is its recognition basis.
Preserve the raw `UNKNOWN` record unchanged; this one-chest observation is not completed-route
acceptance. Current native acceptance for all these new routes remains `evidence_required`.
Existing individual effect/Home acceptance, uninterrupted Enhancement proof, independent recruit
timers, and cadence scope are historical context in [`BACKLOG.md`](../BACKLOG.md), not active
sequencing. The current planning authority is tracker #53, with volatile state in the handoff.

Before invoking a due native runner, the owning service checks the foreground. A healthy game is
left in its current context for route-owned recognition. An exact known BlueStacks launcher can
receive one supported game activity start; the service then requires fresh clean Home or an exact
startup overlay with a recovery owner. Actual launcher restoration followed by a Basic recruit
and verified Home is accepted. Separate cold-process tests verified a full game-process exit,
one corrected MAIN/LAUNCHER start and shared startup recovery to Home. The command matches
the measured icon intent fields but originates from Android shell, while the icon originates
from the BlueStacks launcher. The original Play Games prompt's cause remains unproved; the
latest cold test required no manual Cancel. Account setup, login, CAPTCHA and unknown
foregrounds stop for a human.

Network interruption recovery (#104) is implemented and offline-proven, not live-accepted.
Foreground alone no longer bypasses an exact `Disconnected. Reconnect now?[10054]` dialog.
The shared recognizer requires its current native message/code, measured panel and one isolated
literal Confirm. Other codes, ambiguous targets and manual/unknown contexts grant no recovery input;
the existing independently recognized VIP/Scarlett owners remain separate.

Recovery is opt-in: add `--recover-network-disconnect` to an explicitly authorized supervised native
`serve --live` invocation. It borrows the current runtime owner, service claim/generation fences and
Core lease; it does not acquire a parallel operator. One physical-runtime-scoped SQLite episode
persists its original deadline (at most 90 seconds), one Confirm intent and at most one launcher-only
game launch across processes, routes and UTC resets. Intent is committed before transport. Persistent
or unknown outcomes stop without an identical retry or budget renewal. No force-stop, resource spend,
login handling or generic Confirm is authorized.
After Confirm, dismissal may first expose the interrupted screen with a loading spinner.
That unknown successor permits observation only until the original deadline, not another input
or readiness. Manual states and unrelated modals still stop immediately.


A successful reconnect still needs fresh clean Home or an exact owned startup overlay. The service
records its actual game input separately from system launch and zero route actions, defers that claim,
then requires a fresh normal route claim/binding; recovery earns no daily progress. The typed
recovery-only occurrence disposition preserves all historical run/occurrence/reset identities and
recovery charges without consuming daily/cooldown gameplay eligibility. Ordinary DEFERRED route
results still consume their occurrence. A restart at the launcher cannot bypass an unfinished
episode through ordinary startup or renew its original deadline/launch budget.
Active native capture/dispatch boundaries retain and stop on the interruption rather than using
stale context or recovering through an unresolved gameplay effect. Interrupted Core history is
never silently cleared.
For standalone operator qualification with all controls disabled and no service owner/run, use
`python scripts/pnsctl.py development-session recover-network --live --yes` under current explicit
authorization. It requires the existing canonical database and records its bounded result/captures.
The authorized November 7 native canary sent exactly one Confirm, zero launches and zero spend.
Its immediate successor was the Daily Quest screen plus a loading spinner, so the old guard
stopped as `unexpected_successor`. The source, immediate-before, transport, after and terminal
records remain under `recover-network-20261107T205836212809Z`. A later zero-input observation
showed Home outside the original deadline; it does not make that canary accepted.
Actual-capture replay now proves bounded observation through loading to Home offline.
Finished native recovery, launcher and recovered-route acceptance remain `evidence_required`.

For explicit operator inspection of that returned zero-cost navigation only, use
`python scripts/pnsctl.py development-session recover-network --inspect-only --live --yes`.
The same disabled-control/exclusive-owner admission applies. No input or launch is possible.
Two fresh Home captures, the exact own Confirm record, returned transport, no relaunch, and
no uncertain gameplay effect are required. Existing Core reconciliation and the canonical
episode transition record the inspection; they never clear an uncertain consequential action.
The original source, deadline, counters and raw failed receipt are retained. The new receipt
states `original_canary_accepted=false` and requires a fresh invocation, not replay of old work.

If UTC reset changes during startup before the native runner enters, a genuine checkpoint reset
signal can defer the old claim with zero gameplay consumption. Owner, control, clock, lease,
dispatch and unresolved-action checks still apply; only successful canonical terminal projection
can clear that claim's exact interruption marker. The service then admits a fresh identity on its
normal loop. This lifecycle is offline-proven, including continuous execution without restart.
Incomplete launch transport, invalid startup accounting and all after-runner reset failures retain
inspection stops; the deferral does not claim a gameplay completion or verified Home.

## Local checks

Run focused checks from the repository root:

```text
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_automation_service_contracts \
  tests.test_automation_service_adapters \
  tests.test_automation_service_temporal \
  tests.test_automation_service_scheduler \
  tests.test_automation_service_handlers \
  tests.test_automation_service_campaign \
  tests.test_automation_service_operations
```

The CLI is local and non-authorizing:

```text
PYTHONDONTWRITEBYTECODE=1 python -m automation_service --mode disabled status
PYTHONDONTWRITEBYTECODE=1 python -m automation_service --adapter replay observe
```

### Read-only shadow scheduling (REC-F05)

`shadow`, non-live `run`, and service construction for observation do not seed flow
rows or claim occurrences. CLI shadow opens existing canonical state read-only; an
absent path stays absent and uses an isolated, query-only in-memory schema. Neither
form can execute a real pulse, reserve actions, or acquire a service lease.

Existing enabled/due rows can produce a candidate without starting its handler.
Service, flow, run, action, lease, and clock facts remain unchanged. Initialization
belongs to explicit control and real-execution entrypoints, including the retained
offline `pnsctl` scheduler pulse. Both persisted execution gates still apply.

This is an offline boundary repair, not native acceptance or scheduler enablement.

### Non-consuming selectors (REC-F06)

World, Nova, Recruitment, Campaign, and disabled handlers return `SelectionPlan`,
not gameplay completion. Repeated eligible selections remain available across
restarts without creating runs/actions or consuming an occurrence. The offline
`pnsctl` pulse can therefore report a selected candidate with `result: null`.

Real-runner planning remains behind claim and dispatch fences. A verified
zero-action `ALREADY_COMPLETE` result is accepted only when the handler's matching
`FlowSpec.observation_only_completion` explicitly permits it; registration and
selection alone never establish gameplay success.

### Executor-bound Recruitment exception

The supervised Windows/BlueStacks Recruitment handler is the registered selector exception.
The other explicit native runners are installed by service composition, not ordinary selector
registration. Recruitment's ordinary registry handler remains a non-consuming
`SelectionPlan`; only explicit supervised `serve --live` composition installs
`RecruitmentExecutionHandler`. The coordinator must claim and fence the run before
calling that handler, use its bounded 12-input/3-recruit budget, and project the
verified terminal result through the same canonical state manager.

The runner redeems currently eligible zero-cost Basic, Intermediate, and Advanced
recruits, persists verified per-tier UTC cooldown state, returns to canonical Home,
and derives the next due time from the earliest retained eligibility. Unknown,
uncertain, paid, duplicated, stale-target, or non-Home terminal outcomes block
instead of advancing maintenance state. This code path remains dormant while
the service or Recruitment flow control is disabled; code registration alone cannot execute it.

## Packaging and eventual deployment

`docker/automation-service.Dockerfile` and `compose.automation-service.yml` provide a reproducible
Linux packaging shape with disabled/fake defaults, bounded resources, a read-only code/root
filesystem, and explicit writable state/evidence mounts. The compose file makes no Docker-socket,
libvirt, public-ADB, or runtime-host assumption.

Build and test locally before any future artifact deployment. No deployment is performed by this
roadmap slice; Codex/Cursor is not a NAS production dependency.

## Readiness versus admission

Offline tests establish composition readiness only. They do not promote registry entries, alter
the queue scheduler flag, or admit runtime input. The earlier supervised Campaign navigation
slice covered 1-20-9, 1-15-9, and 2-2-9; those receipts prove navigation only. Later consuming
route acceptance is recorded separately in the backlog. Neither kind of proof production-enables,
registers, or Bliss-validates a route.

The redundant standalone `scripts/supply_depot_bluestacks.py` adapter is retired after offline
call-graph review, independent verification, and focused validation. Supply Depot continues to use
the Home Atlas route. Its current free-only effect/Home acceptance is recorded in the backlog;
permanent service enablement and deployment remain unchanged, with runtime controls currently off.

