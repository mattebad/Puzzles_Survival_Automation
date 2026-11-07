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
  registry has sixteen fixed flow specs, which report `REGISTERED`; this is composition only.
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

Repeat `--flow` for other named routes; the README gives the complete fifteen-route command. Argument order does not
choose scheduler order; due eligibility and existing controls do. The disabled-gates canonical CLI
proof produced zero captures and zero new runs, so it is control evidence only and does not promote
native route acceptance. Facade checks, the ordinary one-battle live-entrypoint retirement, and
the scheduler/facade consumer checks are recorded separately; their counts are not additive.

The fixed native composition binds fifteen canonical routes: Nova, Recruitment, Campaign,
Bioenhancer, Supply, Ultimate, Enhancement, Personal Might, Daily Rewards, Resource Item,
Ruins, Alliance Help, Alliance Donation, Alliance Shop and Daily Shops. The sixteenth fixed
spec is navigation-only `world_map_navigation`, with no `serve --flow`. Passing `--flow` alone
never enables a route.

B adds Ruins/Help; C adds Donation, Alliance Shop and Daily Shops. These are implemented and
offline-proven, not newly live-accepted; production and SQLite runtime controls remain disabled.
Donations count actual successful HOT-tech donations, not ranking points. Alliance Shop requires
one affordable allowlisted Weekly offer or the exact one-star Other fallback, quantity one total.
Daily Shops bounds each approved three-star Chip/Module tab purchase by observed stock and
affordability, with paired item/currency effects. No purchase-effect native acceptance is claimed.

Daily performs at most one current aggregate Claim, then separately claims glowing chests with
same-slot `Claimed` and canonical journal confirmation. Restart-stable reset/slot keys protect
effects; UNKNOWN stops without identical retry, and already-claimed manual work is skipped.
Complete zero-ready scans return to verified Home. The owner-authorized November 7 single-chest
investigation supplied actual ready/Claimed pixels, not completed-route acceptance. Current native
acceptance for all these new routes remains `evidence_required`.
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

