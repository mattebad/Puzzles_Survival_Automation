# Automation service

`automation_service/` is a thin local/offline composition package. It reuses the existing
`safe_action_core` policy, executor, store, action lifecycle, and
`SQLiteSchedulerInvocationRepository`; `tasks.scheduler_task_result` supplies normalized
scheduler-aware results, while `tasks.perception_bundle`, native-frame replay, and existing
Campaign/Home semantics remain the source contracts.

## Boundaries

- Context classification is read-only. Flow handlers own action semantics.
- The service scheduler uses UTC epoch `next_eligible_at` values. It never interprets
  `tasks.scheduler.TaskState.next_due_monotonic` and does not compose two schedulers.
- Fake and replay adapters have zero transport.
- The BlueStacks adapter is supervised-only, requires a flow-bound single-use admission token,
  and can dispatch only through `SafeActionExecutor` with a bound core request/capability. The
  service CLI has no arbitrary ADB, coordinate, shell, tap, remote, or automatic endpoint.
- Production registration and scheduler eligibility remain disabled in
  `tasks/flow_delivery_disabled_production_registry.json`.
- Campaign composition delegates destination policy and atlas navigation to existing
  `tasks.campaign_auto_battle` / `tasks.campaign_atlas` contracts. It never authorizes AP,
  Challenge, Auto Battle, Sweep, Blitz, Auto Complete, or AP refill.
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
- `run_semantic_ocr` owns the sole OCR process boundary. Windows Job Objects and Linux
  process groups contain helpers; success and timeout both drain the tree and reap its root.
  A 250ms cleanup reserve is deducted from the execution budget. Timeout is `UNKNOWN/OCR_DEADLINE`.
- `ScreenDefinition.ocr` is a spawn-picklable `(pixels, psm) -> str` engine;
  `ocr_request` supplies the fixed request or a capture/deadline factory.
  `ocr_recognizer` is pure interpretation of the completed OCR observation and current capture,
  not another OCR callback. Existing provenance normalization still applies.
- Existing capture-bound Supply Depot calls never repair identity or fall back after denial.
  No-identity legacy OCR and other direct native consumers remain held for F17; this
  shared-seam repair does not authorize native route adoption.
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
  UTC rollback blocks claims. A running old-reset occurrence cannot consume the new reset.

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

The supervised Windows/BlueStacks Recruitment service is the one current consuming
handler exception. Its ordinary registry handler remains a non-consuming
`SelectionPlan`; only explicit supervised `serve --live` composition installs
`RecruitmentExecutionHandler`. The coordinator must claim and fence the run before
calling that handler, use its bounded 12-input/3-recruit budget, and project the
verified terminal result through the same canonical state manager.

The runner redeems currently eligible zero-cost Basic, Intermediate, and Advanced
recruits, persists verified per-tier UTC cooldown state, returns to canonical Home,
and derives the next due time from the earliest retained eligibility. Unknown,
uncertain, paid, duplicated, stale-target, or non-Home terminal outcomes block
instead of advancing maintenance state. This code path remains dormant while
registration, service, and Recruitment scheduling are disabled.

## Packaging and eventual deployment

`docker/automation-service.Dockerfile` and `compose.automation-service.yml` provide a reproducible
Linux packaging shape with disabled/fake defaults, bounded resources, a read-only code/root
filesystem, and explicit writable state/evidence mounts. The compose file makes no Docker-socket,
libvirt, public-ADB, or runtime-host assumption.

Build and test locally before any future artifact deployment. No deployment is performed by this
roadmap slice; Codex/Cursor is not a NAS production dependency.

## Readiness versus admission

Offline tests establish composition readiness only. They do not promote registry entries, alter
the queue scheduler flag, or admit runtime input. The supervised Campaign navigation proving slice
is complete: three consecutive post-repair cycles covered 1-20-9, 1-15-9, and 2-2-9, within nine
successful retained results overall. This proves only the BlueStacks navigation boundary; no
family is production-enabled, registered, scheduler-eligible, or Bliss-validated.

The redundant standalone `scripts/supply_depot_bluestacks.py` adapter is retired after offline
call-graph review, independent verification, and focused validation. Supply Depot continues to use
the verified Home Atlas route; free-only gameplay contracts remain evidence-gated and disabled.

