# Recovery operations backlog

This file is the planning record for the operations slice. The tickets are inactive recovery work;
none authorizes a device, host, NAS, VM, ADB, gameplay, credential, token, LLM, MCP, or protected
evidence operation. The direct Android-focused VM remains the selected hosted runtime. Any fallback
is another runtime hosted inside Unraid (an Android VM first, then BlueStacks inside an Unraid Windows
VM); external Windows hardware is not a fallback. A legacy path is never a live fallback: until an
exclusive canonical cutover or an explicit retirement is recorded, the affected flow is disabled.

## Shared operational contract

* `service_control.enabled` is the sole global transport gate and `flow_state.enabled` is the sole
  per-flow enable authority. A static registry default only initializes a missing row as disabled.
* One SQLite state manager, one fenced service lease, one active run, and one runtime input owner are
  required. Claims, generations, reservations, `DISPATCHING`, reconciliation, and terminalization
  are atomic where specified by the foundation tickets. Queue state, receipts, Git fingerprints,
  registries, environment variables, `--live`, and evidence cannot enable or retry a flow.
* A cutover disables the global gate, drains/reconciles active runs, removes or hard-disables every
  old live binding, installs one canonical runner, verifies zero-input behavior for retained replay
  adapters, commits the binding, and only then permits an explicit SQLite enable transition. If any
  old live binding cannot be removed or hard-disabled atomically, the route stays disabled.
* Production is NAS-only: packaged worker, Android/BlueStacks runtime, local OCR, state, evidence,
  monitoring, watchdog, recovery, and startup continue while every external PC is powered off.
  No production external PC, SSH tunnel, PowerShell process, API/token, Cursor/Codex session, LLM,
  MCP, physical Android, or externally maintained service is permitted.
* No operation in this planning change was run. Native records below are future supervised records,
  not claims that old BlueStacks evidence is current Bliss/NAS acceptance.

## Hosted-runtime gate sequence

These gates are ordered for future operators; they are not being executed by this planning change:

1. **Offline composition and exclusive cutover:** foundation contracts, route implementation, replay,
   and scoped fault/crash proofs pass. Keep `service_control.enabled=false` and every
   `flow_state.enabled=false`; remove or hard-disable every old live binding. A missing canonical
   cutover or unresolved route disposition means disabled, never legacy fallback.
2. **Hosted profile and independence (`REC-O02`, `REC-O03`, `REC-O05`):** lock the selected Bliss
   profile, expected account/server guard, unprivileged worker package, private worker-to-VM ADB,
   cache-local SQLite/WAL, restricted evidence, health-gated startup, and no-external-PC operation.
   No external Windows hardware, SSH tunnel, PowerShell, API/token, LLM, MCP, or physical Android
   can be a production prerequisite.
3. **Recovery and operations (`REC-O04`, `REC-O06`, `REC-O07`):** accept optional manual takeover,
   verified backup/restore, bounded worker/game/runtime/VM lifecycle, disk/DB/ADB health, retention,
   status, and fault recovery. Never reboot Unraid or restart with an unresolved consequential effect.
4. **Named current-native records (`REC-O08`, then selected `REC-O10-*`):** one operator/device owner
   at a time, same hosted composition/profile, exact route budget and product approval, independent
   before/action/after/negative/timeout evidence, and explicit per-route disable switch. A row's
   failure does not block unrelated rows, and a row's pass does not enable another row.
5. **Duration gates (`REC-O09`):** complete the distinct 24-hour locked-runtime navigation/health
   stage; only after selected claim-only promotion, complete the distinct 72-hour claim-only
   scheduling stage. Reset, restart, stop, lease, clock, storage, and duplicate-occurrence behavior
   are checked at each stage.
6. **Selected capability soak (`REC-O11`):** run seven-day expanded-task validation and then
   21-day production hardening only for a frozen set of accepted named routes. Final closure states
   accepted selected capabilities, blocked policy expansion, and omitted scope separately; it never
   calls prohibited or policy-deferred routes implemented.
7. **Retirement (`REC-O12`–`REC-O14`):** only after all retained live callers have canonical
   cutovers or explicit disabled retirements, remove duplicate authorities and wrappers. These
   retirements do not depend on O11 and never restore a legacy live path.

## Tickets

### REC-O01 — Coordinate cleanup PR and reconcile legacy backlog
- Task ID: `REC-O01`
- Type: Decision
- Priority: P1
- Status: READY
- Objective: Publish and maintain the operations-owned mapping from every legacy heading in the audited backlog ranges to a deliberate retain/reuse/supersede/defer disposition, while coordinating (not reviewing, opening, pulling, merging, or creating) the separate repository-cleanup PR. Preserve every old status, accepted fact, and evidence pointer; treat a source rename/rebase checkpoint as coordination work, never as a blanket runtime blocker.
- Dependencies: none
- Related work: `GOV-DURABLE-STATE`, `EVIDENCE-RETENTION-HYGIENE`, `STAGE-11-FINAL-RECONCILIATION`, and `RUNTIME-RELIABILITY-MERGE-BOUNDARY` are retained as historical records; their statuses and evidence are not rewritten. The old delivery/queue headings are superseded only as runtime authority by `REC-O12`/`REC-O13`; the old Home/popup wrappers are superseded only by `REC-O14` after cutover.
- Evidence: `docs/archive/backlog-legacy.md` audited at ranges `1-598`, `1099-1641`, `4299-5494`, `5640-6712`, and `7414-7717`; `governance-simplification-plan.md` phases 0–7 and gates 1–38; `docs/runtime-reliability-convergence-status.md`; `docs/pns-operations-runbook.md`.
- Scope: `docs/backlog/operations.md`, `docs/archive/backlog-legacy.md` (read-only coordination), `CURRENT_HANDOFF.md` (read-only coordination), `docs/pns-operations-runbook.md`
- Changes: Keep the reconciliation table below complete and one-row-per-heading for the audited ranges; classify old completed labels as historical rather than canonical readiness; link every new operational ticket by stable `REC-Oxx` ID; record cleanup-PR coordination and exact changed-path comparisons without fetching or reviewing that PR; record source rename/rebase checkpoints only when they affect an owned path; keep legacy work in Related work rather than Dependencies.
- Non-goals: Do not edit `docs/archive/backlog-legacy.md`, `CURRENT_HANDOFF.md`, the contract guide, the index, or any peer backlog file; do not inspect or create a cleanup PR; do not alter evidence, statuses, source, branches, commits, or runtime state.
- Acceptance: (1) Every heading in each audited range has exactly one table row below. (2) Each row names retain/reuse/supersede/defer and either a new owner or explicit historical-completed/no-new-work disposition. (3) No old evidence is deleted, relabeled as current canonical acceptance, or silently changed. (4) Cleanup coordination is explicitly separated from review/fetch/merge and from runtime authorization. (5) No unresolved legacy live authority is presented as a fallback.
- Verification: Prescribed but not executed: a future parser check for one row per heading plus `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_governance_validation tests.test_flow_delivery_authority_consistency`; compare only named paths after the cleanup PR owner supplies its revision.
- Native gate: none for this documentation decision; it grants no host/device access and no runtime authority.
- Integration owner: Main owns shared `docs/archive/backlog-legacy.md` pointers, `CURRENT_HANDOFF.md`, contract/index updates, and the final union/duplicate check; this ticket owns only this document's operations record.
- PR boundary: documentation-only record, branch `recovery/rec-o01`; no PR is created now.
- Rollback: restore this document from its prior version without touching historical backlog or evidence; runtime remains globally disabled.
- Runtime authorization: none; zero input, zero transport, zero state/evidence mutation.
- Completion: reconciliation table and coordination notes are reviewed against the exact audited ranges; this planning completion does not imply any code, native, scheduler, or production readiness.

### REC-O02 — Accept final NAS-only runtime and production adapter profile
- Task ID: `REC-O02`
- Type: Validation
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Define and later accept the final NAS-hosted runtime/profile boundary and the development-to-production adapter transition without silently changing the selected deployment requirement: Bliss direct Android VM plus an unprivileged Unraid worker is the candidate, while BlueStacks evidence from development remains non-canonical until a separately accepted hosted profile.
- Dependencies: `REC-F09`, `REC-F10`, `REC-F11`, `REC-F13`, `REC-F15`
- Related work: `RT-013`, `RT-019`, and `RT-021` are retained/reused for selected Bliss/profile/worker-path facts, but their completed labels are not final production readiness. `RT-014A` is optional viewer evidence and does not reject unattended Bliss. `M5-DECISION` is retained as the historical custom-stack selection; `DQ-FLOW-CAMPAIGN-AUTO-BATTLE-BLUESTACKS` and other BlueStacks successes are reusable development evidence only. `REC-O05` owns packaging/independence details; `REC-O09` and `REC-O11` own duration gates.
- Evidence: `puzzles-survival-deterministic-service_3c9d7823.plan.md` §§2–5, 18–20; `runtime-profile/manifest.json`; `compose.automation-service.yml`; `docker/automation-service.Dockerfile`; retained RT-013/RT-019/RT-021 records named in the plan; `docs/automation-service.md`.
- Scope: `runtime-profile/manifest.json`, `compose.automation-service.yml`, `docker/automation-service.Dockerfile`, `automation_service/session.py`, `automation_service/service.py`
- Changes: Lock profile ID, package, renderer, portrait `800x1280`/160-dpi dimensions, locale, capture contract, ADB endpoint boundary, worker identity, and compatible asset metadata. Exercise the actual Unraid-local worker-to-VM adapter, not an external tunnel. Record Bliss as selected and document exact rejection triggers before any NAS-hosted fallback; if a fallback is needed, keep controller/CV/OCR/state on Unraid and require its own profile and acceptance. Separate development BlueStacks adapter facts from production admission.
- Non-goals: No external-PC production mode, physical Android, public ADB, SSH-tunnel dependency, BlueStacks-on-Linux-Docker claim, runtime migration, game update, account operation, or silent relaxation of the NAS-only rule; no native action is authorized by this record.
- Acceptance: (1) A reproducible hosted profile validates package, display, renderer, locale, capture, private ADB, storage, and worker identity. (2) The worker continues with the external development machine powered off. (3) Profile/asset mismatch causes a global input lock. (4) The selected Bliss profile is either accepted with a documented boundary or rejected only by a named hard trigger and a NAS-hosted fallback record. (5) BlueStacks development evidence is never counted as current production acceptance. (6) No public listener, external token, LLM, MCP, or external PC is needed.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_automation_service_operations tests.test_automation_service_boundaries tests.test_bliss_porting_toolbox`; then a future NAS-local operator record covering profile/offline-independence checks.
- Native gate: required later, supervised and NAS-local only; current native evidence must exercise the selected hosted profile/adapter, with no external PC or token. This ticket itself performs no native work.
- Integration owner: Main owns the canonical profile/adapter schema and shared service gate; route owners include exact caller migrations in their PRs. Serialize changes to `automation_service/session.py` and `automation_service/service.py`.
- PR boundary: one focused profile/adapter acceptance PR or operational record, branch `recovery/rec-o02`; no PR is created now.
- Rollback: disable `service_control` and affected `flow_state` rows; retain the selected profile and backup; never restore a legacy live adapter or external-PC dependency.
- Runtime authorization: none until explicit hosted-profile acceptance and every route-specific gate; no persistent enablement.
- Completion: accepted profile and adapter record is evidence-backed and distinct from 24-hour/72-hour/7-day/21-day readiness.

### REC-O03 — Enforce expected account and server session guard
- Task ID: `REC-O03`
- Type: Story
- Priority: P0
- Status: BLOCKED_NATIVE
- Objective: Add a fail-closed expected-account/server guard that blocks all consequential input on identity mismatch, login/tutorial/new-account, session loss, account-on-another-device, CAPTCHA, or authentication challenge, while leaving login, credentials, tutorial, provisioning, restoration, and account switching manual-only.
- Dependencies: `REC-F09`, `REC-F10`, `REC-F15`
- Related work: `RT-016A` and `M7-AccountGuard` are superseded by this canonical guard design but their retained identity/hard-stop observations remain historical evidence. `GF-MVP-003-SUPERVISED-IDENTITY-AND-PREFLIGHT` is retained as supervised preflight evidence, not unattended account acceptance. `REC-O10` may use this guard only after its current identity prerequisite is accepted.
- Evidence: plan §§2, 5.2, 15, 18; `tasks/runtime_identity.py`; `automation_service/session.py`; `automation_service/service.py`; `docs/runtime-input-safety-policy.md`; the retained account-on-another-device hard-stop observation and pending redacted player/server identity requirement in the plan.
- Scope: `tasks/runtime_identity.py`, `automation_service/session.py`, `automation_service/service.py`, `docs/runtime-input-safety-policy.md`
- Changes: Capture/restrict numeric player/account ID, server/state identifier, and secondary commander evidence (alliance may be optional support); hash or redact normal logs. Require strong verification at startup, after app/Android/VM restart, after session overlays, after manual restoration/takeover, and after TTL expiry. Use lightweight markers only between strong checks. On mismatch or uncertainty, globally lock input, persist evidence, notify once, enter bounded backoff, and await manual restoration; never tap through or repeatedly restart. Reverify before each consequential action.
- Non-goals: No credential storage/input, account switching, login/tutorial/CAPTCHA automation, account recovery, session bypass, generic restart loop, or acceptance based solely on a logged-in-looking screen.
- Acceptance: (1) Expected account/server identity is captured through a redacted/restricted current record and exact TTL. (2) Every named hard-stop state blocks consequential input and releases ownership safely. (3) Strong verification is required at all restart/takeover/restoration boundaries. (4) Expired, missing, mismatched, or contradictory identity yields `GLOBAL_INPUT_LOCK`/manual intervention. (5) No notification, evidence, or cached marker can authorize a mismatch. (6) A clean verified session permits only the already-authorized route gate, not arbitrary input.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_runtime_identity tests.test_automation_service_boundaries tests.test_automation_service_canonical_authority`; future supervised record must show expected, unknown, mismatch, restart, and hard-stop outcomes without credentials.
- Native gate: current redacted identity/server evidence and selected platform/profile prerequisite are required later; they are operator-controlled native gates, not dependencies for the offline guard. No automated account operation or current native input is authorized by this ticket.
- Integration owner: Main owns the identity schema, generation checks, status/notification plumbing, and all session callers; route PRs must include the guard hunks rather than deferring wiring.
- PR boundary: one focused account/session guard PR, branch `recovery/rec-o03`; no PR is created now.
- Rollback: disable global and affected flow gates; preserve redacted evidence; never reinstate account-blind legacy dispatch.
- Runtime authorization: none until the explicit identity record and guard acceptance; zero credentials and zero live input now.
- Completion: guard behavior and evidence are accepted separately from gameplay-route success and from any old completed label.

### REC-O04 — Implement safe manual takeover with fenced pause and reconcile
- Task ID: `REC-O04`
- Type: Story
- Priority: P1
- Status: WAITING_DEPENDENCIES
- Objective: Provide an optional operator takeover that pauses the executor, acquires exclusive device ownership, prevents concurrent daemon input, reconciles all unresolved consequences, and resumes only from a newly classified state with a fresh account check and generation.
- Dependencies: `REC-F09`, `REC-F15`, `REC-O03`
- Related work: `M7-Takeover` and `RT-014A` are superseded/reused: the takeover lifecycle is new canonical work, while RT-014A remains optional private viewer transport evidence and is not a service dependency. `GF-MVP-003-SUPERVISED-IDENTITY-AND-PREFLIGHT` is retained as preflight history only.
- Evidence: plan §§3, 5.2, 15, 18; `automation_service/session.py`; `automation_service/cli.py`; `scripts/bluestacks_native_runtime.py`; `docs/chat-execution-ownership-policy.md`; `docs/pns-operations-runbook.md`.
- Scope: `automation_service/session.py`, `automation_service/cli.py`, `scripts/bluestacks_native_runtime.py`, `docs/chat-execution-ownership-policy.md`
- Changes: Define pause/stop request and new-generation fencing; acquire a single operator lease only after the daemon is paused; verify no unresolved consequential action; enable a private viewer input channel only if separately proven; perform manual work; release lease; capture a fresh frame; require `REC-O03` identity revalidation; reconcile task/action state; resume only from the newly classified state. Viewer observation must remain optional and structurally unable to authorize daemon work.
- Non-goals: No public remote tap API, arbitrary ADB, credential/tutorial/account automation, concurrent operator/daemon input, automatic recovery of unknown consequences, or requirement that unattended service have a viewer.
- Acceptance: (1) Pause fences the next daemon dispatch and creates a new generation. (2) Lease ownership is exclusive and released on every terminal/error path. (3) Takeover is refused while a consequential action is unresolved. (4) Viewer input is private, explicit, and optional. (5) Release always triggers fresh capture, identity check, and reconciliation. (6) Resume cannot reuse the old generation, frame, target, or action reservation.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_development_session tests.test_navigation_development_boundary tests.test_runtime_identity`; future manual-takeover record is supervised and bounded.
- Native gate: optional viewer evidence and the selected platform/profile prerequisite are later operator-controlled native gates, not offline implementation dependencies; no live takeover is authorized now and unattended operation must work without a viewer.
- Integration owner: Main owns lease/generation/session API; the route owner must include pause/reconcile/resume hunks in the same cutover PR.
- PR boundary: one focused takeover/session PR, branch `recovery/rec-o04`; no PR is created now.
- Rollback: global stop and per-flow disable; release the operator lease; leave the old route disabled rather than restoring a second live owner.
- Runtime authorization: none; manual takeover later requires explicit operator authorization and current account/profile checks.
- Completion: takeover is proven race-safe and reconciliation-first, not merely viewer-connected.

### REC-O05 — Package the private NAS-local worker and resource boundaries
- Task ID: `REC-O05`
- Type: Story
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Produce a reproducible unprivileged worker package and deployment boundary with private local ADB, cache-local SQLite/WAL, restricted evidence/config, health-gated autostart, and bounded CPU/RAM/disk use, with no external-PC, token, API, LLM, MCP, or Docker/libvirt authority.
- Dependencies: `REC-F09`, `REC-F10`, `REC-F14`, `REC-F15`
- Related work: `RT-021` is retained/reused for direct Unraid worker-to-VM path evidence, including its bridge refusal and explicitly justified host-network fallback; `RT-015` is superseded by the canonical worker-after-VM health ordering; `RT-019` is reused for profile compatibility. `AUTOMATION-SERVICE` historical packaging records are retained; they do not authorize production.
- Evidence: `docker/automation-service.Dockerfile`; `compose.automation-service.yml`; `runtime-profile/manifest.json`; `docs/automation-service.md`; plan §§2–5, 6, 9, 18, 20; RT-021 retained path/least-privilege observations.
- Scope: `docker/automation-service.Dockerfile`, `compose.automation-service.yml`, `runtime-profile/manifest.json`, `automation_service/cli.py`, `automation_service/service.py`
- Changes: Pin package/assets/local OCR/config versions; run as an unprivileged worker with read-only code/root filesystem and explicit writable cache/state/evidence mounts; keep active SQLite/WAL on cache/NVMe local storage and copy consistent backups to restricted storage; allow only worker-to-VM private ADB; publish no listener and mount no Docker socket or unrestricted libvirt; start worker only after VM/ADB/profile/game/account/storage health; enforce CPU/RAM/evidence quotas and input lock when persistence or disk health fails.
- Non-goals: No NAS host reboot authority, external tunnel, public ADB, Windows host worker, external model/API/token, arbitrary shell/tap endpoint, privileged Android container on the host, or production use of development toolbox/PowerShell.
- Acceptance: (1) Image/package is reproducible from pinned inputs and contains no runtime LLM/MCP/token dependency. (2) Container is unprivileged and network allowlisted to the hosted runtime. (3) SQLite active files remain local cache-backed, never SMB/NFS WAL. (4) Worker stays stopped/backed off until VM, ADB, profile, game, identity, storage, and health gates pass. (5) Quotas and disk thresholds force global input lock before exhaustion. (6) Production remains operational with external PCs off.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_bliss_porting_toolbox tests.test_automation_service_cli tests.test_automation_service_operations`; future NAS-local packaging/startup record must be operator-run.
- Native gate: later NAS deployment smoke requires an accepted selected platform/profile prerequisite and operator authorization; that native gate is not an offline packaging dependency, and no host/device action is authorized now.
- Integration owner: Main owns compose/profile/schema mutation and shared service gate; serialize Docker/compose changes with lifecycle and backup owners.
- PR boundary: one packaging/deployment PR, branch `recovery/rec-o05`; no PR is created now.
- Rollback: stop worker and disable global gate; retain cache/state/backup; do not fall back to an external worker or legacy dispatcher.
- Runtime authorization: none; no deployment or persistent enablement in this plan.
- Completion: package, network, storage, quota, and independence records all pass without host-risk expansion.

### REC-O06 — Verify backup/restore and bounded VM-worker lifecycle
- Task ID: `REC-O06`
- Type: Story
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Define and later verify secured backup/restore plus bounded worker/VM lifecycle recovery, preserving SQLite/action state and refusing restart while a consequential action may have an unknown effect; the worker may never reboot Unraid.
- Dependencies: `REC-F14`, `REC-F15`, `REC-O05`
- Related work: `RT-017` is retained/reused for historical post-provisioning backup hashes and offline restore evidence; `RT-018` is superseded by this bounded lifecycle contract; `RT-011` is retained as tested app/guest/VM restart history, not a production lifecycle pass. `STAGE-11-FINAL-RECONCILIATION` remains historical.
- Evidence: `automation_service/state.py`; `automation_service/service.py`; `scripts/bluestacks_native_runtime.py`; `docs/pns-operations-runbook.md`; plan §§5.2, 9, 15, 18–20; retained RT-017 backup and RT-011 restart records.
- Scope: `automation_service/state.py`, `automation_service/service.py`, `scripts/bluestacks_native_runtime.py`, `compose.automation-service.yml`, `NEW: ops/lifecycle.py`
- Changes: Version and hash qcow2/XML/EFI/GRUB/config backups with restricted access; verify offline restore before use; define worker restart, game restart, Android/runtime restart, and VM stop/start escalation with capped attempts and backoff; reconcile prepared/input-sent/DISPATCHING/UNKNOWN actions, day/reset, marches, queues, leases, and generations before eligibility; require no unresolved consequential effect before any restart; never issue an Unraid host reboot.
- Non-goals: No autonomous NAS reboot, destructive restore over protected state, blind retry after crash/timeout, restart that erases unresolved evidence, external lifecycle service, or claim that old RT-017/RT-011 evidence proves future production cycles.
- Acceptance: (1) Backup integrity and restricted location are verified against source hashes. (2) Restore is proven offline without mutating protected production state. (3) Worker/game/runtime/VM escalation is bounded and health-gated. (4) Unknown or unresolved action blocks restart and input until semantic reconciliation/manual intervention. (5) Five future VM/worker lifecycle cycles preserve day, completion, lease, budget, and action state; no host reboot occurs. (6) Orphaned `DISPATCHING` remains `UNKNOWN` and is never automatically repeated.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_automation_service_state tests.test_scheduler_sqlite tests.test_scheduler_retirement tests.test_safe_action_core`; future operator lifecycle/restore record is separate from unit checks.
- Native gate: controlled NAS-local worker/VM lifecycle and the selected platform/profile prerequisite are later operator-controlled native gates, not offline dependencies; no Unraid reboot and no restart when effect is unknown.
- Integration owner: Main owns state/recovery schema and generation fencing; O05 owns package startup hooks; serialize lifecycle scripts with service/session changes.
- PR boundary: one backup/lifecycle PR or operational record, branch `recovery/rec-o06`; no PR is created now.
- Rollback: stop global service, preserve source and backup artifacts, disable affected rows; never revive old lifecycle authority.
- Runtime authorization: none until explicit operator authorization and backup proof; no host/device operations now.
- Completion: restore and bounded-cycle evidence proves recovery preserves safety state rather than only booting a VM.
### REC-O07 — Operate bounded monitoring, evidence retention, and health recovery
- Task ID: `REC-O07`
- Type: Validation
- Priority: P1
- Status: WAITING_DEPENDENCIES
- Objective: Establish bounded local status, structured logs/evidence retention, health checks, and recovery decisions for disk-full/read-only storage, SQLite contention, ADB/adapter loss, stale frames, process failure, and scheduler lag without creating a telemetry framework or an authorization side channel.
- Dependencies: `REC-F14`, `REC-F15`, `REC-O05`, `REC-O06`
- Related work: `EVIDENCE-RETENTION-HYGIENE` is retained as historical archive-before-removal evidence; `GF-MVP-006-EXECUTABLE-AND-EVIDENCE-INTEGRITY` and `GF-MVP-007-NAMED-SCENARIO-FAILURE-ACCOUNTING` are reused for bounded evidence/accounting semantics, not runtime authority. `RT-012` is retained as a 4-hour observe-only health record; it does not satisfy 24-hour/72-hour/7-day/21-day gates.
- Evidence: `docs/evidence-retention-policy.md`; `docs/evidence-retention-report.md`; `automation_service/service.py`; `automation_service/state.py`; `docs/pns-operations-runbook.md`; plan §§9, 15, 18–20.
- Scope: `automation_service/service.py`, `automation_service/state.py`, `docs/evidence-retention-policy.md`, `docs/pns-operations-runbook.md`, `NEW: ops/health_policy.py`
- Changes: Expose local read-only status for runtime/profile/account state, scheduler due/retry, task modes, breakers, lease, DB/disk/ADB/frame/game/VM health, versions, and recovery counters. Log bounded structured events and before/after/unknown evidence with restricted access, quotas, retention tiers, and archive-before-removal. On storage failure, DB contention, adapter loss, stale/profile mismatch, or repeated recovery, lock input, preserve diagnostics, release ownership, and back off; notifications are optional and never authorize action.
- Non-goals: No external telemetry SaaS, unlimited video/log retention, evidence-driven enablement/retry, arbitrary remote controls, protected-evidence rewrite, or generic popup/health watcher that sends input.
- Acceptance: (1) Status is read-only and cannot claim/reserve/enable/dispatch. (2) Every named health fault maps to a bounded stop, backoff, breaker, or manual escalation. (3) Disk-full/read-only and DB contention never emit input. (4) Evidence quotas stop capture safely before exhaustion and do not delete protected records. (5) ADB/adapter loss and stale frames release ownership without blind retry. (6) Notifications and evidence edits cannot change SQLite eligibility or retry state.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_automation_service_operations tests.test_automation_service_state tests.test_automation_service_boundaries`; future fault records must cover storage, contention, adapter loss, and recovery.
- Native gate: later supervised NAS-local fault exercise only; no telemetry service, host/device access, or protected evidence mutation now.
- Integration owner: Main owns status schema and health gate; O05/O06 own packaging/lifecycle hooks; retain one shared mutation boundary.
- PR boundary: one operations-health PR or record, branch `recovery/rec-o07`; no PR is created now.
- Rollback: disable service/flows and preserve diagnostics; never bypass storage or health locks to regain throughput.
- Runtime authorization: none; optional notification cannot authorize runtime action.
- Completion: bounded health, retention, and recovery records are accepted independently from long-duration soak.

### REC-O08 — Supervise current native World acceptance by scenario
- Task ID: `REC-O08`
- Type: Validation
- Priority: P0
- Status: BLOCKED_NATIVE
- Objective: Run a future supervised current-native World acceptance ledger whose acceptance unit is one uninterrupted Home → World → Search → Home run with one device owner, one run token, one exact budget, and one truthful total-input ledger. `REC-O08-WORLD-NAV`, `REC-O08-WORLD-SEARCH`, and `REC-O08-WORLD-RETURN` are segment subchecks within that run, not independently sufficient acceptance; this ticket never enables a route by itself.
- Dependencies: `REC-F13`, `REC-F15`, `REC-O02`, `REC-O03`
- Related work: `DQ-FLOW-WORLD-STAMINA-ENGINE`, `DQ-FLOW-GATHERING`, `CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION`, and `AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE` are retained as offline/BlueStacks or navigation history only. Their accepted labels do not constitute current native acceptance. `REC-O10` consumes only named scenario records, never a blanket O08 pass.
- Evidence: plan §§6–8, 13.5, 15, 19–20; `scripts/world_map_navigation_bluestacks.py`; `tasks/world_stamina.py`; `automation_service/handlers.py`; `tests/test_world_map_navigation_bluestacks.py`; current profile/identity requirements from `REC-O02`/`REC-O03`.
- Scope: `scripts/world_map_navigation_bluestacks.py`, `tasks/world_stamina.py`, `automation_service/handlers.py`, `automation_service/session.py`, `tests/test_world_map_navigation_bluestacks.py`
- Changes: Create one parent operator record `REC-O08-WORLD-HOME-WORLD-SEARCH-HOME` plus segment subchecks `REC-O08-WORLD-NAV`, `REC-O08-WORLD-SEARCH`, and `REC-O08-WORLD-RETURN` for only the Home → World → Search → Home path. The parent run uses one device owner, hosted profile/account, run token, exact total input/time budget, and evidence directory without resetting, stopping, or substituting a segment between transitions; the ledger totals every input across all three subchecks truthfully. Each subcheck fixes its segment action ceiling, expected successor, bounded allowed-popup handling, unknown/profile/reset stop conditions, and evidence slice. Use current-frame target binding and no generic Back/click. Lair and gathering canaries are not part of O08; their native acceptance belongs to the corresponding O10 R-ticket scenarios.
#### REC-O08 scenario records

Each record below is a segment subcheck within the single parent run; no segment passes independently or substitutes for the uninterrupted whole-route record. All remain disabled until the parent run's exact operator, device/profile, run token, total budget, approval, and evidence record pass.

| Record ID | Path segment | Implementation dependency | Segment subcheck boundary | Authority |
|---|---|---|---|---|
| `REC-O08-WORLD-NAV` | Home → World | `REC-F13` | Current Home frame binds the World target and proves the expected World successor within the action/time ceiling; no resource, march, generic tap, or stale/profile/unknown continuation. | Subcheck only; parent run remains disabled until the named whole-route record has an explicit budget/approval. |
| `REC-O08-WORLD-SEARCH` | World → Search | `REC-F13` | Current World frame binds Search and proves the expected Search successor with bounded allowlisted popup handling; no node, gathering, march, stale/profile/unknown, or contradictory continuation. | Subcheck only; parent run remains disabled until the named whole-route record has an explicit budget/approval. |
| `REC-O08-WORLD-RETURN` | Search → Home | `REC-F13` | Current Search frame binds the safe return and proves Home; an unknown/contradictory popup, profile/reset mismatch, timeout, or disable state emits zero further input and leaves the parent row disabled. | Subcheck only; parent run remains disabled until the named whole-route record has an explicit budget/approval. |

- Non-goals: No one giant World checklist, Lair/gathering canary, batch dispatch, permanent enablement, public/native host access, external PC, token/LLM/MCP, route promotion from static fixtures, or substitution of old BlueStacks successes for current hosted evidence.
- Acceptance: (1) One uninterrupted current-native Home→World→Search→Home run, with one run token and one device owner/profile, proves each expected successor and records a truthful total input ledger across the full path; no reset, stop, or independent segment substitution is accepted. (2) Segment subchecks have their own action ceilings, preconditions, outcomes, and evidence slices, but none can pass O08 without the parent whole-route record. (3) Navigation proves expected World/Search/Home successors and safe return with zero unintended input. (4) Bounded allowlisted popup handling proves one exact close/reclassification path; unknown/contradictory popup fails closed. (5) Unknown, stale, profile/account mismatch, reset crossing, adapter loss, timeout, or disable state produces zero further input and leaves the parent run disabled. (6) A parent scenario record may be consumed by O10 without implying any Lair or gathering route passed.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_world_map_navigation_bluestacks tests.test_automation_service_handlers tests.test_automation_service_boundaries`; native evidence is a separate operator record, not a test command.
- Native gate: this ticket is itself a future supervised current-native gate; one operator/device owner, exact named budget and explicit authorization are mandatory. No current device/host action occurs now.
- Integration owner: Main owns the scenario registry/ledger and O08 record schema; route owners supply exact implementation dependency and route verifier for each scenario. Serialize ledger schema changes.
- PR boundary: operational validation records, branch `recovery/rec-o08`; no code PR or native run now.
- Rollback: stop global gate, disable scenario row, release lease, retain evidence; never use a legacy World dispatcher as fallback.
- Runtime authorization: none until the named scenario has explicit authorization; O08 cannot enable routes.
- Completion: one uninterrupted parent Home→World→Search→Home record and its three segment subchecks pass with a truthful total input ledger; segment records cannot substitute for the parent record, and O08 completion is not a route authorization.

### REC-O09 — Pilot the hosted service for 24 hours then 72 hours
- Task ID: `REC-O09`
- Type: Validation
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Exercise the hosted service progressively through two distinct validation records: first a locked-runtime 24-hour navigation/health pilot (`REC-O09-24H-NAVIGATION`), then a separate 72-hour bounded claim-only continuous-scheduling pilot (`REC-O09-72H-CLAIM-ONLY`) only after the 24-hour record and accepted named O10 claim-only canaries. The `REC-O09` umbrella closes only when both stage records pass; reset, restart, stop, recovery, and ownership behavior remain recorded independently from platform proof.
- Dependencies: `REC-O08`, `REC-F16`
- Related work: `RT-012` is retained as the passed 4-hour observe-only baseline but does not satisfy this ticket. `RT-011`, `RT-015`, and `RT-018` are historical restart/order/lifecycle evidence reused as prerequisites, not current pilot acceptance. `REC-O10` route records and `REC-O11` long soak remain separate.
- Evidence: plan §§5.2–5.3, 7, 15, 18–20; `automation_service/service.py`; `automation_service/scheduler.py`; `automation_service/state.py`; `docs/runtime-reliability-convergence-status.md`; `compose.automation-service.yml`.
- Scope: `automation_service/service.py`, `automation_service/scheduler.py`, `automation_service/state.py`, `compose.automation-service.yml`, `NEW: ops/soak_runner.py`
- Changes: Record two distinct stages, `REC-O09-24H-NAVIGATION` and `REC-O09-72H-CLAIM-ONLY`, with locked profile, account, exact selected capabilities, budgets, quiet periods, poll intervals, health limits, and owner. The 24-hour stage is navigation/health only unless separately authorized; it must cross a reset boundary and exercise controlled worker/game/runtime stop/restart without host reboot. Its accepted validation record is a prerequisite for selected O10 claim-only canaries. The 72-hour stage requires an explicit list of accepted named O10 claim-only record IDs after that 24-hour record; it must preserve deterministic occurrence keys, backoff, reset identity, one active run, and no tight loop, and it must not wait on or imply unrelated O10 rows.
- Non-goals: No claim that 24 hours authorizes arbitrary routes, no 72-hour run before claim-only prerequisites, no seven-day/21-day substitution, no Unraid reboot, external PC, token/LLM/MCP, prohibited spend/strategic flow, or second scheduler.
- Acceptance: (1) The `REC-O09-24H-NAVIGATION` record proves locked-profile navigation/health continuity, reset reconciliation, controlled stop/restart, no duplicate claims, no leaked leases, and no NAS regression. (2) Selected O10 claim-only canaries may begin only after that named 24-hour record and each has its own approval, budget, evidence, and disabled row. (3) The `REC-O09-72H-CLAIM-ONLY` record starts only after its exact named claim-only O10 records pass and proves continuous wake scheduling with bounded polling, quiet periods, restart persistence, and no duplicate/unknown retry. (4) Each stage has separate budgets, evidence, and stop reasons. (5) Account/session, storage, profile, clock rollback, adapter loss, or unresolved action stops input safely. (6) Neither stage enables omitted or policy-deferred routes.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_automation_service_scheduler tests.test_automation_service_temporal tests.test_pnsctl_scheduler_pulse tests.test_automation_service_state`; future stages require hosted operator records.
- Native gate: current NAS-hosted runtime operation only after O08 and foundation gates; no native/device operation by authors. `REC-O09-24H-NAVIGATION` precedes selected O10 claim-only canaries; `REC-O09-72H-CLAIM-ONLY` requires those named records and explicit promotion. The 24-hour gate precedes repeated/unattended claim-only execution; neither stage enables routes outside its named set.
- Integration owner: Main owns service/scheduler state and staged pilot records; route owners own selected route evidence. Serialize pilot mutations with O05–O07.
- PR boundary: operational pilot records, branch `recovery/rec-o09`; no run or PR now.
- Rollback: global stop, disable selected rows, preserve stage evidence and unresolved actions; never start a second live scheduler or legacy fallback.
- Runtime authorization: none; each stage needs explicit later authorization and its own start/stop record.
- Completion: both named stage records (`REC-O09-24H-NAVIGATION` and `REC-O09-72H-CLAIM-ONLY`) pass their own criteria and the `REC-O09` umbrella records that 24-hour → selected named O10 claim canaries → 72-hour completion; this is not final 7-day/21-day completion.

### REC-O10 — Maintain route-specific current-native acceptance ledger
- Task ID: `REC-O10`
- Type: Validation
- Priority: P0
- Status: BLOCKED_NATIVE
- Objective: Maintain a route-by-route supervised current-native acceptance ledger for every retained route, with each scenario independently dispatchable, its exact implementation dependency, named budget/approval, independent positive/negative/recovery criteria, and disabled authority until that named record passes. The common stage prerequisite is the exact `REC-O09-24H-NAVIGATION` validation record, not completion of the `REC-O09` umbrella; O10 is a ledger/validation epic, not one generic “validate all” checklist and not a global gate for D12.
- Dependencies: `REC-O09-24H-NAVIGATION`, `REC-O02`, `REC-O03`, `REC-O05`, `REC-O07`, `REC-F13`, `REC-F15`
- Related work: Every old DQ/RT/GF/Campaign heading in the reconciliation table is retained as historical or superseded only at its stated boundary. `M6-DQ-TRANSITION-CORPUS` remains a distinct evidence promotion; standalone legacy-native recruitment and Ruins successes are reusable evidence inputs but not current canonical acceptance. `REC-O08` supplies only named World records. `REC-D12` must depend on the exact qualifying O10 scenario IDs selected for its routine, never on umbrella O10 completion.
- Evidence: plan §§13–20; `docs/automation-service.md`; `docs/daily-quest-execution-matrix.md`; `tasks/daily_quest_execution_matrix.json`; `tasks/product_authority.py`; `tasks/runtime_identity.py`; route modules/tests named in the scenario ledger below. Static fixtures and old BlueStacks records are provenance/replay inputs only.
- Scope: `automation_service/registry.py`, `automation_service/handlers.py`, `automation_service/session.py`, `tasks/daily_quest_execution_matrix.json`, `tasks/flow_delivery_product_policy.json`
- Changes: For every scenario below, record route implementation dependency, selected hosted profile/account, exact input/resource/currency/march/queue budget, explicit product approval, operator/device owner, current-native before/action/after/negative/timeout evidence, verifier, outcome, and disable/rollback switch. Keep each scenario disabled until its own record passes both SQLite gates and route cutover. Use `REC-O10-<route>` record IDs as stable per-route acceptance dependencies. Each selected claim-only row used by `REC-O09-72H-CLAIM-ONLY` must be named explicitly in that stage record; it may proceed after `REC-O09-24H-NAVIGATION` without waiting for the `REC-O09` umbrella. D12 may consume only a named qualifying subset (for example the selected ordinary-claim/milestone/free/recruitment/help/Praise/Nova records), and may not wait on unrelated or prohibited routes.
- Non-goals: No single batch acceptance, no route enablement by this epic, no policy decision hidden in a canary, no generic retry, no external PC/token/LLM/MCP, no current-native claim from legacy BlueStacks evidence, and no requirement that prohibited or policy-deferred flows be accepted.
- Acceptance: (1) Every scenario below has an independent ledger row and dispatch assignment. (2) Each row names its own implementation dependency, budget/approval, positive postcondition, denial boundaries, and current-native evidence. (3) A missing/failed row leaves only that row disabled and never activates another. (4) O10 completion is the set of accepted named rows, not a global “all routes” boolean or completion of the O09 umbrella. (5) The O09 72-hour stage consumes only its exact accepted named O10 claim-canary records, while O10 remains independent of unrelated rows. (6) D12 integration names exact qualifying O10 record IDs and remains independent of unselected routes. (7) Resource routes retain `ResourceEffectAuthority` until parity is observable. (8) Historical success is explicitly reusable evidence but never canonical readiness.
- Verification: Prescribed but not executed: each row uses its route owner’s existing focused Python unittest module and verifier; shared ledger checks use `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_automation_service_handlers tests.test_automation_service_scheduler tests.test_automation_service_boundaries tests.test_resource_effect_authority_store`. These commands do not replace the named current-native record.
- Native gate: mandatory per named route record, one supervised device owner at a time, exact budget and explicit approval, same hosted composition/profile, current evidence, and route-specific stop rules. Selected O10 claim-only canaries additionally require the named `REC-O09-24H-NAVIGATION` record; no native work is authorized now.
- Integration owner: Main owns the shared route ledger, registry, SQLite gates, and scenario-record schema; each Foundation/Daily/Resource owner owns its route implementation and exact verifier. Shared registry/CLI/schema mutation is serialized; route work is otherwise independent.
- PR boundary: operational ledger and per-route records, branch `recovery/rec-o10`; no giant code PR and no PR/run now.
- Rollback: disable only the affected row and global gate as needed; preserve evidence and resource authority; never restore a second live route or legacy fallback.
- Runtime authorization: none until the named scenario's approval, budget, prerequisites, and both SQLite gates are accepted.
- Completion: the ledger contains accepted selected rows and explicit blocked/deferred rows; named rows may feed `REC-O09-72H-CLAIM-ONLY` after the 24-hour record, but O10 does not close the O09 umbrella, enable a route, or call omitted scope implemented.

#### REC-O10 route scenario ledger

Each row is independently dispatchable only after its named dependency, exact budget, explicit approval,
and current-native evidence are present. `REC-O10-*` identifiers are stable acceptance-record IDs; they
are not an umbrella enable switch. The route's SQLite row remains disabled otherwise.

| Record ID | Named route scenario | Route implementation dependency | Independent acceptance boundary | Authority |
|---|---|---|---|---|
| `REC-O10-D01` | Daily catalog/identity reconciliation | `REC-D01` | Selected-Daily identity, Main-negative, no-premium policy, and unsupported-row disposition are current and reproducible; no input. | Disabled until this named record has an explicit budget/approval (or explicit observe-only disposition). |
| `REC-O10-D02` | Selected Daily inventory/reset provider | `REC-D02` | Selected tab, bounded rows, overlap, current game-day, clipped/ambiguous abstention, and reset guard reconcile without dispatch. | Disabled until this named record has an explicit budget/approval (or explicit observe-only disposition). |
| `REC-O10-D03` | Ordinary aggregate Daily Claim | `REC-D03` | One aggregate ordinary free non-milestone Claim per distinct durable ready batch/occurrence within a reset proves the same selected-Daily source, reset, and batch identity, with a verified aggregate Claim-control transition/exhaustion and positive points delta together; either missing signal leaves the claim unresolved/nonretryable with no retry or claimed state. Main, milestone, row-local, clipped, stale, paid, unknown, and unchanged cases input zero. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D04` | Activity milestone chest | `REC-D04` | One ready free chest at an identified threshold proves the same chest identity, threshold, and reset through a `ready`→`claimed/opened` transition; a points increase alone is insufficient. Locked, static, non-free, wrong-reset, unchanged, or unresolved cases deny. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D05` | Ultimate zero-resource Daily Flee | `REC-D05` | Exact safe entry/Flee route proves Daily completion without combat/premium/AP; unsafe or ambiguous successor disables only this row. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D06` | Bioenhancer free Research | `REC-D06` | One Free Research 1x, quantity one, proves same-day result/cooldown and Daily progress; paid 10x/static/unknown cases deny. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D07A` | Basic Noah’s Tavern five free singles | `REC-D07` | Each selected reset-scoped single has one 600-second window, exact count/progress, no 10x/premium, and no duplicate pulse. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D07B` | Independent Intermediate/Advanced recruitment maintenance | `REC-D07` | Each tier has its own due/cooldown/queue state, persistent effect, bounded dispatch, and lease release while waiting; Basic evidence cannot prove another tier. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D08` | Alliance Help | `REC-D08` | Help/Help All is semantically bound and zero-cost; one request/result or proven no-request postcondition reconciles without Claim attribution or retry. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D09` | Personal Might Praise | `REC-D09` | Current Personal Might screen and exact Praise target produce one control-change postcondition; Nova/static/Claim/repeat negatives deny. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D10` | Supply Depot free collections | `REC-D10` | One bounded all-free hold uses the exact current Free Food target, known zero cost/quantity one, and an observed `1..10` attempt count; its successor proves Free disappeared/exhaustion and the reconciled resource effect. Independently observe actual current-reset Daily progress before and after: partial progress is a normal successful bounded-maintenance outcome, and only an observed `5/5` claims Daily completion; the held gesture is not per-unit Daily proof. Paid-next, unknown reward/cost/attempts, overlay, stale, unchanged, or unresolved states stop immediately. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D11` | Nova one-free-pulse | `REC-D11` | One exact free Nova pulse proves cooldown/attempt and postcondition while remaining distinct from Personal Might Praise. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-D12` | Selected useful Daily routine | `REC-D12` | A named subset of already accepted O10 records reaches the selected candidate target (candidate 30 points where approved), separates ordinary/milestone Claim, interleaves recruitment safely, and does not claim full 150 or depend on unrelated O10 rows. | Disabled until the selected subset and its explicit budget/approval are recorded. |
| `REC-O10-R01` | ResourceEffectAuthority parity boundary | `REC-R01` | Occurrence, quantity, reserve, delta, unknown-effect, crash, and changed-hypothesis behavior agrees observably before any effectful route is enabled. | Disabled until parity is accepted and each consuming route has a named budget/approval. |
| `REC-O10-R02` | One 1K Food use | `REC-R02` | Exact item identity, quantity one, ordinary resource delta, no premium, and canonical Home postcondition; no Daily credit inference. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R03` | Gear one-star enhancement | `REC-R03` | Equipped Gear, one-star material, quantity one, exact Enhance, and level/material delta; Auto Select/high-star/other actions deny. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R04` | Chip one-star enhancement | `REC-R04` | Equipped Chip identity and same one-star/quantity/result contract; Gear/Module mismatch and unsafe controls deny. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R05` | Module one-star enhancement | `REC-R05` | Equipped Module identity and same one-star/quantity/result contract; cross-family target/material mismatch denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R06` | Fighter T8/current-maximum training | `REC-R06` | Explicitly approved tier/quantity and ordinary cost start one queue with timer/result; box, queue conflict, reserve breach, or wrong family denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R07` | Rider T1 training | `REC-R07` | One once-daily T1 bounded training proves exact queue/resource delta; no boxes, bulk default, or wrong family. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R08` | Shooter T8/250 training | `REC-R08` | One approved 250-quantity bounded start proves queue and cost; wrong tier, box, premium, or queue ambiguity denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R09` | Vehicle T1/current-maximum training | `REC-R09` | One approved Vehicle queue start proves exact cost/timer; no strategic upgrade or occupied queue. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R10` | Campaign destination navigation | `REC-R10` | Each configured destination (1-15-9, 1-20-9, 2-2-9) independently reaches verified destination and safe return with no AP spend. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R11` | Campaign AP Auto Battle | `REC-R11` | One approved stage/count proves AP delta, result, reserve, and no refill; Sweep/Blitz/battle/static route mismatch denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R12` | Ruins zero-cost NPC challenge | `REC-R12` | Exact safe NPC challenge entry/result and canonical return prove no premium/combat ambiguity; unknown opponent/lineup denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R13` | Ruins per-category chest maintenance | `REC-R13` | Category-specific ready chest and continuation state persist independently of challenge/ordinary/milestone; unknown reward or duplicate claim denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R14` | Nano Material six-hour maintenance | `REC-R14` | Idle/active/completed/claim/start transitions and six-hour timer reconcile without duplicate start. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R15` | Nanoweapon Normal Craft | `REC-R15` | Normal Craft, 100 parts, 12-hour duration, one active queue, one reset/start and completion claim; Exclusive/Production/unknown cost denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R16` | Direct Home→World→Search gathering foundation | `REC-R16` | Resource category, level 5, free node/slot, current-frame node, march/return facts are proven; no dispatch is implied by foundation acceptance. | Disabled until this named record has an explicit budget/approval (or explicit navigation-only disposition). |
| `REC-O10-R17` | Wood 30000 gathering | `REC-R17` | Wood target and 30000 variant prove bounded march/return and ledger delta; occupancy/target drift/no slot denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R18` | Steel 6000 gathering | `REC-R17` | Steel target and 6000 variant independently prove same engine/ledger; Wood evidence cannot authorize Steel. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R19` | Gas 1500 gathering/reveal | `REC-R18` | Gas reveal/rebind, 1500 target, node identity and bounded march result prove; unknown reveal or node drift denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-R20` | Zombie Lair Home maintenance | `REC-R19` | Level 30–55, Join, stamina 28, march availability, notification/result and exact consume attribution prove; level 60/refill/unknown formation denies. | Disabled until this named record has an explicit budget/approval. |
| `REC-O10-P01` | Ruins Shop policy route | `REC-P01` | Product owner approves exact item/currency/budget (if any) and current native offer/receipt; no Buy occurs before approval. | Disabled until named policy and budget approval. |
| `REC-O10-P02` | Rare Earth Shop policy route | `REC-P02` | Explicit product contract, currency/reserve, item/quantity, and receipt are accepted; otherwise permanently disabled/observe-only. | Disabled until named policy and budget approval. |
| `REC-O10-P03` | Alliance Shop policy route | `REC-P03` | Explicit route, offer, currency, quantity, budget, and post-balance receipt pass; no inference from another shop. | Disabled until named policy and budget approval. |
| `REC-O10-P04` | Hero Upgrade policy route | `REC-P04` | Exact hero identity/material/level/cost and product approval pass; Wali/Wally ambiguity or premium path blocks. | Disabled until named policy and budget approval. |
| `REC-O10-P05` | Hero Duel participation | `REC-P05` | Only an explicit PvP product decision can define opponent/lineup/attempt/result budget; absent decision remains disabled. | Disabled until named policy and budget approval. |
| `REC-O10-P06` | Building Upgrade | `REC-P06` | Exact building, prerequisite, queue, resources, duration, and approval pass; generic building evidence cannot authorize spend. | Disabled until named policy and budget approval. |
| `REC-O10-P07` | Tech Upgrade | `REC-P07` | Exact research target/prerequisites/queue/resource budget and approval pass; no automatic resource pack. | Disabled until named policy and budget approval. |
| `REC-O10-P08` | Alliance Tech Donation | `REC-P08` | Exact target/resource/count/cap and approved ordinary-resource budget reconcile; no premium or unknown target. | Disabled until named policy and budget approval. |
| `REC-O10-P09` | 180-minute speedup | `REC-P09` | Exact item, queue, duration, quantity one, waste/cap and approval pass; universal/premium/unsafe queue denies. | Disabled until named policy and budget approval. |
| `REC-O10-P10` | ResourceBuildingBoost | `REC-P10` | Exact building, duration, cost, current boost state and product budget pass; policy-disabled otherwise. | Disabled until named policy and budget approval. |
| `REC-O10-P11` | RareEarthPit income discovery | `REC-P11` | Discovery and policy decision identify whether any route exists; no income or claim authority from discovery alone. | Disabled until named policy and budget approval. |
| `REC-O10-P12` | BuyBox purchase | `REC-P12` | Separate BuyBox policy, item/currency/quantity/reserve and receipt acceptance; never merge with ResourceBuildingBoost or other shops. | Disabled until named policy and budget approval. |

### REC-O11 — Run progressive seven-day and 21-day NAS-only closure
- Task ID: `REC-O11`
- Type: Validation
- Priority: P0
- Status: WAITING_DEPENDENCIES
- Objective: Close the user's explicitly approved final capability matrix through a seven-day expanded-task soak followed by a 21-day NAS-only hardening run. Final acceptance requires implementation, canonical caller cutover, named current-native acceptance, and REC-O12/O13/O14 retirement proof for every retained, non-policy-deferred capability in that matrix; a smaller portfolio requires an explicit user decision, and the initial 30-point routine or navigation-only pilot is never project completion.
- Dependencies: `REC-O02`, `REC-O03`, `REC-O04`, `REC-O05`, `REC-O06`, `REC-O07`, `REC-O09`, `REC-O10`, `REC-D12`, `REC-O12`, `REC-O13`, `REC-O14`
- Related work: `harden-and-soak` and old Stage 10/11 headings are retained as historical roadmap context; `RT-012` is only the 4-hour baseline. `REC-O10` contributes only accepted named scenario records selected for this closure. `REC-P01`–`REC-P12` policy-deferred routes remain excluded unless separately approved and accepted. Historical recruitment five-window and Ruins actual-claim successes remain reusable evidence but do not close current canonical acceptance.
- Evidence: plan §§2, 5.2–5.3, 15, 18–20; `docs/runtime-reliability-convergence-status.md`; `docs/automation-service.md`; `compose.automation-service.yml`; `automation_service/service.py`; `automation_service/state.py`.
- Scope: `automation_service/service.py`, `automation_service/state.py`, `automation_service/scheduler.py`, `compose.automation-service.yml`, `NEW: ops/production_soak.py`
- Changes: Freeze the user-approved final capability set and route-record IDs before each stage; enumerate every retained, non-policy-deferred capability with its implementation, canonical caller cutover, named current-native record, and O12–O14 retirement proof. If the user explicitly selects a smaller portfolio, record each excluded retained capability and reason rather than silently shrinking scope. Run seven-day observe/dry-run/approved-task validation, then 21-day production hardening on the hosted NAS composition with external PCs off. Treat the initial 30-point routine and any navigation-only pilot as intermediate evidence only, never final completion. Monitor active-run cardinality, leases/generations, duplicate occurrence/action keys, unknown reconciliation, OCR worker lifetime, DB/WAL/disk growth, CPU/RAM/temperature/NAS latency, ADB/runtime recovery, reset boundaries, quiet periods, and policy breakers. Keep prohibited premium/strategic/PvP/policy-deferred routes disabled; publish a final matrix distinguishing accepted retained capabilities, explicit user-approved exclusions, blocked policy expansion, and omitted scope.
- Non-goals: No external-PC operator dependency, token/LLM/MCP/API, host reboot, stealth/evasion, silent policy expansion, automatic shrink of the final portfolio, treating the initial 30-point routine or navigation-only pilot as completion, full 150-point claim, acceptance from labels alone, or claim that omitted scope is implemented.
- Acceptance: (1) Seven-day stage passes only for the frozen user-approved final matrix, with implementation and canonical caller cutover proof plus a named current-native acceptance record for every retained, non-policy-deferred capability in scope; no unsafe authorization, duplicate completion, stuck loop, unreconciled effect, ownership leak, or unbounded worker. (2) REC-O12, REC-O13, and REC-O14 each provide their required retirement/canonical-authority proofs before final acceptance, while none depends on O11. (3) 21-day stage separately passes NAS resource/reliability limits, restart/reset/recovery, storage retention, and no measurable regression. (4) External PCs may be powered off throughout. (5) Every disabled/prohibited/policy-deferred capability remains listed as blocked/deferred/not implemented, and any smaller final portfolio has an explicit user decision and recorded exclusions. (6) The initial 30-point routine and navigation-only pilot remain intermediate evidence and cannot satisfy project completion. (7) Final closure names all accepted in-scope capabilities, exact evidence, exclusions, and policy blocks; no old completed label substitutes for it. (8) Any fault stops/locks affected scope and preserves evidence.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_automation_service_scheduler tests.test_automation_service_state tests.test_automation_service_boundaries tests.test_resource_effect_authority_store`; future seven-day and 21-day NAS operator records are mandatory.
- Native gate: future hosted-runtime operation only after O02–O10 selected prerequisites, each retained non-policy-deferred in-scope capability's named current-native record, user-approved final capability matrix, and O12–O14 cutover/retirement proofs; no native/device actions now. Seven-day then 21-day gates are distinct and neither promotes policy-deferred routes.
- Integration owner: Main owns frozen capability matrix and final closure record; route owners provide selected O10 records and O12–O14 cutover/retirement proofs for retained accepted capabilities. Serialize closure-state mutation; O12–O14 themselves never depend on O11.
- PR boundary: operational soak/closure records, branch `recovery/rec-o11`; no run or PR now.
- Rollback: global stop and disable affected rows; preserve backups/evidence and narrow selected scope; never enable legacy or omitted routes to keep the soak green.
- Runtime authorization: none until explicit selected-capability budget, profile, account, and hosted-run authorization.
- Completion: seven-day and 21-day records are accepted separately only after the user-approved final capability matrix is fully accounted for, every retained non-policy-deferred in-scope capability has implementation/cutover/current-native evidence, O12–O14 retirement proofs are present, and policy-deferred/omitted scope is explicit; a 30-point routine or navigation-only pilot never closes the project.

### REC-O12 — Retire delivery receipts and legacy runtime authority after cutover
- Task ID: `REC-O12`
- Type: Retirement
- Priority: P1
- Status: WAITING_DEPENDENCIES
- Objective: Remove receipts, Git/content fingerprints, queue activation, delegated leases, conductor runtime state, and other development-delivery authority from the live path only after every retained caller has an exclusive canonical cutover or an explicit disabled retirement; leave no live shim or legacy fallback.
- Dependencies: `REC-F13`, `REC-F14`, `REC-F15`, `REC-F16`, `REC-D03`, `REC-D05`, `REC-D07`, `REC-D08`, `REC-D09`, `REC-D10`, `REC-D11`, `REC-R02`, `REC-R03`, `REC-R04`, `REC-R05`, `REC-R06`, `REC-R07`, `REC-R08`, `REC-R09`, `REC-R10`, `REC-R11`, `REC-R12`, `REC-R13`, `REC-R14`, `REC-R15`, `REC-R16`, `REC-R17`, `REC-R18`
- Related work: `AUTONOMOUS-BLUESTACKS-FLOW-DELIVERY-ORCHESTRATOR`, `AUTONOMOUS-BLUESTACKS-FLOW-DELIVERY-IDE-NATIVE-HARDENING`, `AUTONOMOUS-BLUESTACKS-FLOW-DELIVERY-IDE-NATIVE-RECEIPT-CLOSURE`, `FLOW-DELIVERY-PRETOOLUSE-TASK-ENFORCEMENT`, `FLOW-DELIVERY-PARENT-CONVERSATION-ROLLOVER`, and `FLOW-DELIVERY-TOKEN-AND-CONTEXT-HYGIENE` are retained as historical development workflow records and superseded as runtime authority. `REC-O11` is intentionally not a dependency; retirement follows code cutovers/explicit route retirements, not final soak closure.
- Evidence: governance-simplification-plan.md §§3, 6, 7, 23, 24; `scripts/flow_delivery_control.py`; `scripts/pnsctl.py`; `tasks/flow_delivery_queue.json`; `tasks/flow_delivery_disabled_production_registry.json`; `docs/chat-execution-ownership-policy.md`.
- Scope: `scripts/flow_delivery_control.py`, `scripts/pnsctl.py`, `tasks/flow_delivery_queue.json`, `tasks/flow_delivery_disabled_production_registry.json`, `automation_service/service.py`
- Changes: Inventory every live caller and route; disable global service gate; drain/reconcile active runs; remove or hard-disable receipt/queue/Git/conductor/flow-delivery leases and wrappers; route all remaining input through the SQLite gates, fenced service lease, canonical session, and action executor; keep retained adapters replay/fixture-only and structurally zero-input; record explicit retirements for omitted flows.
- Non-goals: No deletion of historical docs/evidence, no migration of old queue state into production, no fallback to old scheduler/receipt/lease authority, no removal of ResourceEffectAuthority before R01 parity, no O11 dependency or circular closure.
- Acceptance: (1) Every retained live caller maps to an accepted exclusive cutover or explicit disabled retirement; these outcomes are sufficient to close this retirement without waiting for prohibited policy approval. The inventory explicitly accounts for every legacy Lair input caller: while `REC-R19` remains `BLOCKED_POLICY`, each is explicitly disabled-retired, removed, or hard-disabled; no Lair implementation or acceptance is implied. (2) Every policy-deferred capability has no live bypass, and no policy approval is needed merely to keep it disabled or remove its authority. (3) Repository/import review finds no live receipt/Git/queue/conductor transport authority. (4) Old adapters cannot claim, reserve, acquire transport, or call ADB. (5) Both SQLite gates and generation checks remain necessary for manual and scheduled input. (6) Resource routes retain effect authority until parity. (7) A failed cutover leaves route disabled, never legacy-live.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_flow_delivery_authority_consistency tests.test_delegated_runtime_receipts tests.test_scheduler_retirement tests.test_automation_service_canonical_authority`; future repository import scan is scoped to touched paths.
- Native gate: no direct native gate for removing authority; all route-specific native records and explicit retirements must exist before removal. Historical native evidence remains immutable and non-authorizing.
- Integration owner: Main owns `pnsctl`, SQLite gates, service lease, registry, and shared cutover transaction; route owners must deliver complete caller migration in their PRs. Serialize shared-file deletion/hard-disable.
- PR boundary: one focused retirement PR, branch `recovery/rec-o12`; no PR is created now.
- Rollback: stop global service and disable rows; restore code only for forensic/reference use, never its runtime authority.
- Runtime authorization: none during retirement; no live shim.
- Completion: old delivery machinery is absent or zero-input in the live path and the canonical path is complete for every retained route.

### REC-O13 — Retire duplicate registries, scheduler branches, and ledgers
- Task ID: `REC-O13`
- Type: Retirement
- Priority: P1
- Status: WAITING_DEPENDENCIES
- Objective: Retire duplicate static registries, legacy scheduler/CLI branches, matrix/queue runtime reads, and route-local ledgers after route parity and caller migration, while preserving historical documents as non-runtime records.
- Dependencies: `REC-F13`, `REC-F14`, `REC-F15`, `REC-F16`, `REC-D01`, `REC-D02`, `REC-D03`, `REC-D04`, `REC-D07`, `REC-D08`, `REC-D09`, `REC-D10`, `REC-D11`, `REC-R01`, `REC-R02`, `REC-R03`, `REC-R04`, `REC-R05`, `REC-R06`, `REC-R07`, `REC-R08`, `REC-R09`, `REC-R10`, `REC-R11`, `REC-R12`, `REC-R13`, `REC-R14`, `REC-R15`, `REC-R16`, `REC-R17`, `REC-R18`
- Related work: `CAMPAIGN-AND-ULTIMATE-CHALLENGE-FLOW-SCOPE-CORRECTION`, `FLOW-PRODUCT-POLICY-RECONCILIATION-20260723`, all old M5/M6/GNB/DQ matrix headings, `GF-MVP-001-AUTHORITY-BASELINE`, and `GF-MVP-006-EXECUTABLE-AND-EVIDENCE-INTEGRITY` are retained as historical reconciliation/evidence. `REC-O11` is not a dependency. `tasks/daily_quest_execution_matrix.json` and delivery registries may remain readable project-management records but cannot remain runtime authority.
- Evidence: governance-simplification-plan.md §§6–7, 23; `tasks/flow_delivery_queue.json`; `tasks/daily_quest_execution_matrix.json`; `tasks/flow_delivery_disabled_production_registry.json`; `tasks/flow_delivery_bluestacks_registry.json`; `automation_service/registry.py`; `automation_service/scheduler.py`.
- Scope: `tasks/flow_delivery_queue.json`, `tasks/daily_quest_execution_matrix.json`, `tasks/flow_delivery_disabled_production_registry.json`, `tasks/flow_delivery_bluestacks_registry.json`, `scripts/pnsctl.py`
- Changes: Search every import/read/write of duplicate registries, matrix, queue, route-local ledgers, and legacy CLI scheduler branches; migrate each live caller to static `FlowSpec` plus SQLite state or explicitly retire it; remove runtime reads and enable decisions; preserve files/docs for history with clear non-authority boundary; retain ResourceEffectAuthority behind canonical actions until R01 parity.
- Non-goals: No historical rewrite/deletion, no automatic migration of conflicting mutable statuses, no generic registry compatibility shim, no O11 dependency, no route enablement during deletion, and no use of evidence files as a replacement authority.
- Acceptance: (1) Search/import evidence shows no runtime read of retired registries/matrix/queue/route-local ledger. (2) Every caller has a canonical owner or explicit disabled retirement; these outcomes are sufficient to close this retirement without waiting for prohibited policy approval. The inventory explicitly accounts for every legacy Lair input caller: while `REC-R19` remains `BLOCKED_POLICY`, each is explicitly disabled-retired, removed, or hard-disabled; no Lair implementation or acceptance is implied. (3) Every policy-deferred capability has no live bypass, and no policy approval is needed merely to keep it disabled or remove its authority. (4) CLI/status/scheduler all read the same SQLite gates/state. (5) Old files remain historical and cannot enable/retry/dispatch. (6) Duplicate scheduler branches cannot select a second occurrence or active run. (7) Failure leaves global/per-flow gates disabled rather than old authority restored.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_scheduler_retirement tests.test_automation_service_canonical_authority tests.test_automation_service_cli tests.test_flow_delivery_authority_consistency`; future scoped import/read scan is required.
- Native gate: none for retirement itself; route cutovers and explicit route retirements, not old native labels, are prerequisites. No live runtime action now.
- Integration owner: Main owns registry/CLI/scheduler shared files and integration search; each route owner must identify exact callers. Serialize all shared registry/CLI mutations.
- PR boundary: one focused registry/scheduler retirement PR, branch `recovery/rec-o13`; no PR is created now.
- Rollback: stop/disable canonical service and retain historical files; do not restore their runtime reads or a second scheduler.
- Runtime authorization: none; retirement cannot enable a route.
- Completion: one canonical runtime authority remains, historical registries are non-authoritative, and no live shim survives.

### REC-O14 — Retire duplicate Home, Back, popup, perception, and accounting wrappers
- Task ID: `REC-O14`
- Type: Retirement
- Priority: P1
- Status: WAITING_DEPENDENCIES
- Objective: Consolidate duplicate Home/Back/popup/perception/fresh-frame/input-accounting wrappers behind the canonical router, overlay manager, session, and executor after every caller migrates; keep compact evidence truthful and handle any colon/ADS filename migration as a separate user-protected change.
- Dependencies: `REC-F01`, `REC-F02`, `REC-F03`, `REC-F09`, `REC-F11`, `REC-F13`, `REC-F14`, `REC-F15`, `REC-F17`, `REC-D03`, `REC-D08`, `REC-D09`, `REC-D10`, `REC-D11`, `REC-R10`, `REC-R12`
- Related work: `VIP-GET-PTS-POPUP-DISMISSAL`, `TOOLS-HOME-BASE-ATLAS-BLUESTACKS`, `HOME-ATLAS-LOCALIZATION-RESTORATION`, `HOME-ATLAS-VERIFIED-ROUTE-INTEGRATION`, `HOME-ATLAS-VERIFIED-ROUTE-SEAM-CLOSURE`, `SUPPLY-DEPOT-VERIFIED-ROUTE-INTEGRATION`, `SUPPLY-DEPOT-RADIAL-TARGET-BINDING-CLOSURE`, `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE`, `VISION-SEMANTIC-OCR-CROP-PIPELINE`, `BLUESTACKS-HOME-SAFE-EXIT-BINDING`, `HOME-NAVIGATION-OBSERVABILITY`, `HOME-NAVIGATION-BOUNDED-SESSION-CALIBRATION`, and `RUNTIME-INPUT-CAPABILITY-FIREWALL` are retained as historical or reused after caller migration. `REC-O11` is not a dependency; this retirement follows route cutovers/explicit retirements.
- Evidence: governance-simplification-plan.md §§6–7, 23–24; `scripts/bluestacks_popup_recognition.py`; `scripts/startup_recovery.py`; `scripts/world_map_navigation_bluestacks.py`; `automation_service/screens.py`; `automation_service/overlays.py`; `docs/runtime-input-safety-policy.md`.
- Scope: `scripts/bluestacks_popup_recognition.py`, `scripts/startup_recovery.py`, `scripts/world_map_navigation_bluestacks.py`, `automation_service/screens.py`, `automation_service/overlays.py`
- Changes: Inventory all callers; route VIP/Get Pts, exit dialogs, known modals, Home recognition, Back semantics, bounded settle/reclassification, fresh-frame identity, target binding, input accounting, successor checks, and compact run evidence through canonical owners; retain route semantics and explicit per-screen Back allowlists; remove duplicate transport/recognition/ledger wrappers only after zero live callers remain. Any evidence filename colon/Windows ADS migration is a separate narrowly authorized user-protected task, never bundled into this retirement.
- Non-goals: No blind Back/close, generic popup watcher, full-frame-hash authority, protected evidence rewrite/rename, filename migration, source fixture deletion, broad perception rewrite, O11 dependency, or live fallback to route-local wrappers.
- Acceptance: (1) Each retired wrapper has zero live callers or is structurally zero-input replay-only. (2) One canonical overlay recognizer/transport and one Home/Back/perception/accounting owner remain. (3) Unknown/contradictory overlay or successor emits zero input and releases ownership. (4) Animated full-frame changes with unchanged authoritative ROIs remain valid; changed ROIs fail closed. (5) Compact evidence records outcome and provenance without enabling/retrying. (6) Protected evidence and colon/ADS paths remain untouched until a separate explicit migration decision.
- Verification: Prescribed but not executed: `PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_startup_recovery tests.test_vip_points_popup tests.test_home_nav_recognition tests.test_automation_service_boundaries tests.test_perception_bundle`; future scoped call-graph/import review is required.
- Native gate: no direct native gate for wrapper deletion; route-native cutovers and explicit retirements must precede it. No current device/host/evidence operation is authorized.
- Integration owner: Main owns canonical screens/overlays/session/executor and shared callers; route owners must migrate every caller in their focused PR. Serialize `automation_service/screens.py`, `automation_service/overlays.py`, and shared wrapper removals.
- PR boundary: one focused wrapper-retirement PR, branch `recovery/rec-o14`; no PR is created now.
- Rollback: disable affected flows and preserve canonical state/evidence; never restore duplicate live wrappers or rewrite protected files.
- Runtime authorization: none; no evidence filename migration or live action.
- Completion: duplicate live ownership is absent, compact evidence remains truthful, and any ADS/colon migration is explicitly separate.

## Legacy-heading reconciliation

The following table covers all 148 third-level task headings in `docs/archive/backlog-legacy.md`, including compact ID-only headings. All 148 are task records; there are no non-task third-level headings. `##` headings are section markers and are intentionally not rows. “Retain — historical completed/no new work” preserves accepted evidence without treating a legacy status as canonical readiness. “Reuse” names facts that a new ticket may consume but does not promote. “Supersede” means only the specified runtime...

| Legacy heading (exact ID/title) | Disposition | New owner or historical disposition |
|---|---|---|
| `GOV-DURABLE-STATE` — Establish durable agent governance and state contracts | retain/reuse | Historical completed/no new work; canonical runtime migration is `REC-O12`/`REC-O13`. |
| `TOOLS-BLUESTACKS-FLOW-CAPTURE` — Build a practical BlueStacks manual flow collector | retain | Historical completed/no new work; development capture only. |
| `EVIDENCE-RETENTION-HYGIENE` — Audit and safely compact local evidence | retain/reuse | Historical passed record; bounded operational retention/health is `REC-O07`; cleanup coordination is `REC-O01`. |
| `M5-CUSTOM-BASELINE` — Benchmark incumbent deterministic stack | retain/reuse | Historical passed benchmark; `REC-O02` reuses stack facts, no new benchmark required. |
| `M5-AIRTEST` — Evaluate policy-constrained Airtest adapter | retain | Historical rejected/no new work; no Airtest production dependency. |
| `M5-MAA` — Evaluate policy-constrained MaaFramework adapter | retain | Historical rejected/no new work; no MaaFramework production dependency. |
| `M5-DECISION` — Select final deterministic control stack | retain/reuse | Historical passed custom-stack decision; `REC-O02` reuses it without changing NAS-only deployment. |
| `M6-DQ-BOOTSTRAP` — Capture Daily Quest bootstrap corpus | retain/reuse | Historical passed corpus; route records in `REC-O10` may reuse provenance, never current native acceptance. |
| `M6-DQ-TRANSITION-CORPUS` — Promote live transition evidence | defer | `REC-O10-D03`/selected claim records; pending evidence promotion remains distinct. |
| `M7-SAFE-ACTION-CORE` — Implement minimum supervised-action safety core | retain/reuse | Historical accepted offline/supervised safety; foundation/session gates and `REC-O10` reuse it, no new ticket solely for old completion. |
| `M7-Takeover` — Integrate safe manual takeover with controller | supersede | `REC-O04`; retained historical design/evidence. |
| `M7-AccountGuard` — Implement fail-closed account/session guard | supersede | `REC-O03`; retained hard-stop evidence, current identity still required. |
| `RT-001` — Preserve working Bliss rollback baseline | retain | Historical passed/no new work; backup/lifecycle extension is `REC-O06`. |
| `RT-002` — Document current VM XML and GRUB behavior | retain/reuse | Historical passed; `REC-O02` and `REC-O06` reuse profile/rollback facts. |
| `RT-003` — Test smallest VirtIO-GPU/VirGL configuration | retain | Historical passed/no new work; no new graphics trial absent hard rejection. |
| `RT-004` — Verify accelerated renderer and host GPU use | retain | Historical passed/no new work; not a production-duration gate. |
| `RT-005` — Decide graphics gate | retain/reuse | Historical passed selection; `REC-O02` preserves its rejection triggers. |
| `RT-006` — Implement unattended boot entry | retain/reuse | Historical passed saved-entry boot; `REC-O05`/`REC-O06` own hosted ordering/lifecycle. |
| `RT-007` — Lock portrait display profile | retain/reuse | Historical passed effective profile; `REC-O02` revalidates profile compatibility. |
| `RT-008` — Secure or strictly isolate ADB | retain/reuse | Historical passed private isolation; `REC-O02`/`REC-O05` require production-local boundary. |
| `RT-009` — Build and run input-fidelity test | retain | Historical passed non-game fidelity/no new work; route-native records remain required. |
| `RT-010` — Build and run capture-fidelity test | retain | Historical passed capture fidelity/no new work; `REC-O07` monitors current health. |
| `RT-011` — Execute restart matrix | retain/reuse | Historical passed restart matrix; `REC-O06` owns bounded production lifecycle. |
| `RT-012` — Run 4-hour Unraid-local observe-only runtime-selection soak | retain/reuse | Historical passed 4-hour baseline; `REC-O09`/`REC-O11` own later duration gates. |
| `RT-013` — Final Bliss pass/fail and runtime-profile decision | retain/reuse | Historical passed Bliss selection; `REC-O02` owns final hosted acceptance without silent change. |
| `RT-014A` — Prove optional private post-VirGL viewer transport | defer | Optional viewer evidence reused by `REC-O04`; never unattended-service dependency. |
| `RT-015` — Document VM autostart and worker ordering | supersede | `REC-O05`; retained documentation facts, no host reboot validation. |
| `RT-016A` — Capture and verify expected account/server identity evidence | supersede | `REC-O03`; old pending identity requirement remains explicit. |
| `RT-017` — Create secured post-provisioning runtime recovery backup | retain/reuse | Historical passed backup evidence; `REC-O06` owns future operational restore/cycles. |
| `RT-018` — Define narrow local VM lifecycle-control boundary | supersede | `REC-O06`; no Unraid reboot authority. |
| `RT-019` — Lock and version final runtime-profile manifest | retain/reuse | Historical passed manifest/schema; `REC-O02` consumes compatibility contract. |
| `RT-021` — Prove unprivileged Unraid worker-to-VM ADB path | retain/reuse | Historical passed worker path; `REC-O02`/`REC-O05` require current hosted independence. |
| `MVP-STARTUP-NORMALIZATION` — Validate Cash Mall-to-Home/Base startup slice | retain/reuse | Historical passed startup slice; `REC-O02`/`REC-O14` reuse semantics, no new live authority. |
| `AUTONOMOUS-BLUESTACKS-FLOW-DELIVERY-ORCHESTRATOR` | supersede | `REC-O12`; historical offline delivery machinery remains non-runtime. |
| `AUTONOMOUS-BLUESTACKS-FLOW-DELIVERY-IDE-NATIVE-HARDENING` | supersede | `REC-O12`; historical IDE workflow only, no production dependency. |
| `AUTONOMOUS-BLUESTACKS-FLOW-DELIVERY-IDE-NATIVE-RECEIPT-CLOSURE` | supersede | `REC-O12`; receipts cannot remain runtime authority. |
| `FLOW-DELIVERY-PRETOOLUSE-TASK-ENFORCEMENT` | retain/supersede | Historical process control retained; runtime authority removed by `REC-O12`. |
| `FLOW-DELIVERY-REVIEW-SNAPSHOT-SECRET-SCAN-ISOLATION` | retain | Historical completed/no new work; evidence protection reused by `REC-O07`. |
| `FLOW-DELIVERY-PARENT-CONVERSATION-ROLLOVER` | retain | Historical completed/no new work; not runtime state, no replacement needed. |
| `FLOW-DELIVERY-TOKEN-AND-CONTEXT-HYGIENE` | retain | Historical completed/no new work; production has no token dependency. |
| `CAMPAIGN-AND-ULTIMATE-CHALLENGE-FLOW-SCOPE-CORRECTION` | retain/reuse | Historical completed policy correction; route-specific acceptance is `REC-O10`. |
| `CAMPAIGN-ATLAS-BACKLOG-DEPENDENCY-RECONCILIATION` | retain/reuse | Historical authority reconciliation; `REC-O01` preserves mapping, `REC-O10-R10` consumes route facts. |
| `CAMPAIGN-ATLAS-SURVEY-CONTRACT-AND-COLLECTOR-PREP` | retain | Historical offline prep/no new work; native acceptance remains per `REC-O10-R10`. |
| `CAMPAIGN-ATLAS-NATIVE-SURVEY-AND-VALIDATION` | retain/reuse | Historical native survey evidence; not current hosted production acceptance. |
| `CAMPAIGN-ATLAS-NAVIGATION-INTEGRATION-AND-REPLAY` | retain/reuse | Historical zero-transport replay; `REC-O10-R10` requires current route record. |
| `CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION` | retain/reuse | Historical navigation canaries; AP route remains `REC-O10-R11` and policy-gated. |
| `AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE` | retain/reuse | Historical BlueStacks navigation success; current native/h hosted acceptance is `REC-O10-R10`. |
| `FLOW-PRODUCT-POLICY-RECONCILIATION-20260723` | retain/reuse | Historical policy classification; route budgets/approvals belong to `REC-O10` and Resource `REC-Pxx`. |
| `GF-MVP-001-AUTHORITY-BASELINE` | retain/reuse | Historical baseline; canonical shared mutation control is Foundation plus `REC-O12`/`REC-O13`. |
| `GF-MVP-002-MINIMUM-CONTRACT-V2` | retain/reuse | Historical contract; route-specific current acceptance is `REC-O10`. |
| `GF-MVP-003-SUPERVISED-IDENTITY-AND-PREFLIGHT` | retain/reuse | Historical supervised identity/preflight; `REC-O03` requires current strong guard evidence. |
| `GF-MVP-004-LOCALIZE-FIRST-HOME-DRIVER` | retain/reuse | Historical Home localization; duplicate wrapper retirement is `REC-O14`. |
| `GF-MVP-005-PRODUCTION-PATH-REPLAY` | retain/reuse | Historical zero-transport replay; does not authorize current production. |
| `GF-MVP-006-EXECUTABLE-AND-EVIDENCE-INTEGRITY` | retain/reuse | Historical evidence/integrity acceptance; bounded operations are `REC-O07`. |
| `GF-MVP-007-NAMED-SCENARIO-FAILURE-ACCOUNTING` | retain/reuse | Historical named budget/accounting pattern; each O08/O10 record requires its own budget. |
| `GF-MVP-008-NOVA-NAVIGATION-ROUTE-MIGRATION` | retain/reuse | Historical Nova navigation; current named route record is `REC-O10-D11`. |
| `GF-MVP-009-NOVA-NAVIGATION-LIVE-CANARY` | retain/reuse | Historical BlueStacks canary; not current hosted native acceptance. |
| `GF-NOVA-PRAISE-SUPERVISED-20260722` | retain/reuse | Historical supervised Praise; current Personal Might route is `REC-O10-D09`, separate from Nova. |
| `GF-MVP-010-LIVE-EVIDENCE-TO-REPLAY` | defer | Historical ready replay promotion; current route evidence/ledger is `REC-O10`; do not imply implementation. |
| `DQ-FLOW-RESOURCE-BOOST` | defer | Policy/resource route is `REC-P10` plus `REC-O10-P10`; remains disabled without named decision/budget. |
| `CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY` | retain/reuse | Historical BlueStacks AP canary; current hosted Campaign AP acceptance is `REC-O10-R11`. |
| `STAGE-11-FINAL-RECONCILIATION` | retain | Historical completed/no new work; final selected-capability closure is `REC-O11`. |
| `RUNTIME-RELIABILITY-MERGE-BOUNDARY` | retain | Historical completed merge boundary/no new work; cleanup coordination only is `REC-O01`. |
| `HOME-ATLAS-LOCALIZATION-RESTORATION` | defer | Foundation localization owner `REC-F12`; `REC-O14` retires duplicate wrappers only after that cutover. |
| `MVP-QUEST-TO-CLAIM` — Complete one supervised Daily Quest vertical slice | defer | Current claim work is `REC-O10-D03`; a selected routine may consume it through `REC-O10-D12`; the old MVP label is not current acceptance. |
| `GNB-PHASE-A` — Complete normalized authorized-trial manifest | retain/reuse | Historical manifest facts remain reusable by `REC-F13`; no runtime authority or native readiness follows. |
| `GNB-PHASE-B` — Calibrate reference geometry to Bliss | retain/reuse | Historical geometry calibration remains profile evidence for `REC-O02`/`REC-O14`; current profile acceptance is separate. |
| `GNB-PHASE-C` — Prepare Bliss profile, navigation, and required popups | retain/reuse | Historical profile/navigation facts may inform `REC-O02`, `REC-O08`, and `REC-O14`; no old label authorizes input. |
| `GNB-PHASE-D` — Complete supervised Praise-to-exact-Claim slice | defer | Current Personal Might/Praise is `REC-O10-D09`; any Claim still requires its own named record. |
| `GNB-PHASE-E/F` — Free Daily Activities, then persistence/scheduler | supersede | Historical roadmap; current route records are `REC-O10`, while persisted scheduler authority is `REC-F14` and delivery authority retires under `REC-O12`/`REC-O13`. |
| `GNB-PHASE-E-DAILY-CLAIMS-OFFLINE` — Generalize available Daily Claim contract | supersede | Canonical implementation/acceptance is `REC-D03` and `REC-O10-D03`; legacy offline contract cannot enable a route. |
| `GNB-PHASE-E-MILESTONES-OFFLINE` — Add activity milestone-chest contract | supersede | Canonical implementation/acceptance is `REC-D04` and `REC-O10-D04`; old offline completion remains historical. |
| `GNB-PHASE-E-DEPOT-OFFLINE` — Add free Supply Depot collection contract | supersede | Canonical implementation/acceptance is `REC-D10` and `REC-O10-D10`; no old fixture authorizes collection. |
| `GNB-PHASE-E-RECRUITMENT-OFFLINE` — Add free recruitment contract | supersede | Canonical implementation/acceptance is `REC-D07` and selected `REC-O10-D07A`/`REC-O10-D07B`; legacy work is not current native proof. |
| `GNB-PHASE-F-OFFLINE` — Define serializable task state and one-pulse scheduler | retain/reuse | Historical state/scheduler contract is reused by `REC-F14`; runtime authority still comes only from SQLite gates. |
| `GNB-PHASE-F-SQLITE` — Persist task state alongside the safety journal | supersede | Canonical persisted task state is `REC-F14`; the old record cannot remain a second runtime authority. |
| `GNB-PHASE-F-INTEGRATION` — Couple one-pulse scheduler to persisted task state | supersede | Canonical scheduler/state cutover is `REC-F14`; duplicate branches are retired by `REC-O13`. |
| `DQ-CATALOG-RECONCILIATION` | retain/reuse | Historical catalog facts feed `REC-D01`; current route acceptance is `REC-O10-D01`. |
| `DQ-COVERAGE-MATRIX` | retain/reuse | Historical coverage mapping feeds `REC-D01` and selected `REC-O10-D12`; it is not a blanket route gate. |
| `DQ-FOUNDATION-DAILY-INVENTORY` | retain/reuse | Historical inventory/reset contract feeds `REC-D02` and `REC-O10-D02`; current evidence is required. |
| `DQ-CLAIM-DAILY` | supersede | Canonical free ordinary claim is `REC-D03` with named native record `REC-O10-D03`. |
| `DQ-CLAIM-MILESTONE` | supersede | Canonical free milestone chest is `REC-D04` with named native record `REC-O10-D04`. |
| `DQ-PERSISTENCE` | retain/reuse | Historical persistence facts feed `REC-F14`; no legacy scheduler state may authorize work. |
| `DQ-SCHEDULER` | supersede | Canonical one-pulse scheduling is `REC-F14`; duplicate scheduler branches are retired under `REC-O13`. |
| `DQ-RUNTIME-INTEGRATION-GATE` | supersede | Runtime integration authority moves to `REC-O12`/`REC-O13` plus the SQLite gates; old gate labels remain historical. |
| `DQ-FLOW-ALLIANCE-HELP` | supersede | Canonical route is `REC-D08` with current record `REC-O10-D08`; no generic Help fallback. |
| `DQ-FLOW-PERSONAL-MIGHT-PRAISE` | supersede | Canonical route is `REC-D09` with current record `REC-O10-D09`; Nova and Claim remain distinct. |
| `DQ-FLOW-BIOENHANCER` | supersede | Canonical route is `REC-D06` with current record `REC-O10-D06`; paid/static cases remain denied. |
| `DQ-FLOW-SUPPLY-DEPOT` | supersede | Canonical route is `REC-D10` with current record `REC-O10-D10`; free-only boundaries remain explicit. |
| `DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION` | supersede | Current one-item resource boundary is `REC-O10-R02`; old BlueStacks integration is provenance only. |
| `VIP-GET-PTS-POPUP-DISMISSAL` | supersede | Popup ownership and safe dismissal retire into `REC-O14`; no generic popup watcher remains live. |
| `TOOLS-HOME-BASE-ATLAS-BLUESTACKS` | retain/reuse | Historical Home/Atlas navigation is reused by `REC-O08`/`REC-O14`; old BlueStacks success is not current native acceptance. |
| `TOOLS-HOME-ATLAS-DIRECT-PAN-PLANNER` | retain/reuse | Historical direct-pan geometry informs canonical Home/Atlas ownership in `REC-O14`; no route enablement follows. |
| `TOOLS-HOME-ATLAS-TROOP-TRAINING-ENTRY-MIGRATION` | retain/reuse | Historical entry migration feeds `REC-O10-R06`–`REC-O10-R09`; each training scenario remains independently gated. |
| `HOME-ATLAS-RECOVERY-AWARE-VIEWPORT-PLANNING` | retain/reuse | Recovery-aware viewport facts feed `REC-O14`; stale/profile/unknown states still fail closed. |
| `TOOLS-HOME-ATLAS-SEMANTIC-REGISTRY-COMPLETION` | supersede | Registry ownership is canonicalized by `REC-O13` with Home/perception wrappers in `REC-O14`; legacy registry cannot dispatch. |
| `RUNTIME-IMMUTABLE-FRAME-PERCEPTION-BUNDLE` | retain/reuse | Historical immutable-frame/perception contract feeds `REC-O14`; authoritative ROIs, not full-frame hashes, govern safety. |
| `RUNTIME-RESUMABLE-NAVIGATION-SESSIONS` | retain/reuse | Session/generation facts feed `REC-F15` and `REC-O14`; old resumability cannot bypass a fresh classification. |
| `ARCH-NAVIGATION-AUTOMATION-ROADMAP` | retain | Historical roadmap/no new work; route-specific current ownership is recorded in `REC-O08`/`REC-O10`. |
| `VISION-SEMANTIC-OCR-CROP-PIPELINE` | retain/reuse | Historical OCR/perception pipeline feeds `REC-O14` and `REC-O07`; no OCR result alone authorizes input. |
| `VISION-NATIVE-FRAME-REPLAY-HARNESS` | retain/reuse | Replay evidence remains fixture/research input for `REC-O10`; it cannot substitute for current native evidence. |
| `HOME-SHARED-RADIAL-SEMANTIC-CONTRACT` | retain/reuse | Shared radial semantics feed `REC-O14`; target binding remains current-frame and fail-closed. |
| `BLUESTACKS-HOME-SAFE-EXIT-BINDING` | supersede | Canonical safe exit/Back ownership is `REC-O14`; legacy BlueStacks binding cannot remain live. |
| `RUNTIME-INPUT-CAPABILITY-FIREWALL` | supersede | Canonical input firewall is the Foundation/session boundary plus `REC-O14`; old wrappers cannot authorize input. |
| `VISION-NATIVE-FRAME-MUTATION-CORPUS` | retain/reuse | Historical mutation corpus remains replay evidence for `REC-O14`; no native readiness is inferred. |
| `HOME-NAVIGATION-OBSERVABILITY` | retain/reuse | Bounded local navigation status feeds `REC-O07`/`REC-O14`; it is read-only and non-authorizing. |
| `HOME-NAVIGATION-BOUNDED-SESSION-CALIBRATION` | retain/reuse | Historical calibration feeds `REC-F15`/`REC-O14`; current profile/account checks remain mandatory. |
| `HOME-ATLAS-VERIFIED-ROUTE-INTEGRATION` | retain/reuse | Historical route integration feeds `REC-O08` for Home→World→Search→Home and `REC-O14`; current evidence is separate. |
| `HOME-ATLAS-VERIFIED-ROUTE-SEAM-CLOSURE` | retain/reuse | Historical seam closure is reusable navigation evidence for `REC-O08`/`REC-O14`, never current route authority. |
| `SUPPLY-DEPOT-VERIFIED-ROUTE-INTEGRATION` | retain/reuse | Historical Supply Depot integration feeds `REC-O10-D10`; current native free-only acceptance remains independent. |
| `SUPPLY-DEPOT-VERIFIED-ROUTE-SEAM-CLOSURE` | retain/reuse | Historical seam evidence feeds `REC-O10-D10`; unknown reward/paid-next cases still stop. |
| `NOVA-PRAISE-HOME-ATLAS-MIGRATION` | defer | Current Nova pulse is `REC-O10-D11`; Personal Might Praise is separately `REC-O10-D09`. |
| `NOAHS-TAVERN-HOME-ATLAS-MIGRATION` | defer | Current recruitment records are `REC-O10-D07A` and `REC-O10-D07B`; old migration is not native acceptance. |
| `TROOP-TRAINING-VERIFIED-NAVIGATION-CONVERGENCE` | retain/reuse | Historical convergence feeds independent `REC-O10-R06`–`REC-O10-R09` records. |
| `TROOP-TRAINING-END-TO-END-CONSOLIDATION` | retain/reuse | Historical consolidation remains reusable only; each fighter/rider/shooter/vehicle route keeps its own `REC-O10` record. |
| `ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION` | defer | Current Gear/Chip/Module records are `REC-O10-R03`–`REC-O10-R05`; BlueStacks evidence is not current native proof. |
| `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION-FINAL-READINESS` | retain/reuse | Historical blocked/readiness record remains context; selected route and retirement ownership is `REC-O10`/`REC-O12`/`REC-O14`, with no old readiness claim. |
| `SUPPLY-DEPOT-VERIFIED-ROUTE-LIVE-BINDER-EVIDENCE` | retain/reuse | Historical binder evidence feeds `REC-O10-D10`; it does not authorize a current collection. |
| `SUPPLY-DEPOT-RADIAL-TARGET-BINDING-CLOSURE` | retain/reuse | Historical target-binding evidence feeds `REC-O10-D10`/`REC-O14`; current-frame identity remains required. |
| `SUPPLY-DEPOT-VERIFIED-ROUTE-LIVE-BINDER-EVIDENCE-RENEWAL` | retain/reuse | Historical renewal evidence feeds `REC-O07`/`REC-O10-D10`; no evidence renewal silently enables a route. |
| `ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION` | retain/reuse | Historical zero-resource Daily Flee integration feeds `REC-O10-D05`; BlueStacks evidence is provenance only. |
| `ULTIMATE-CHALLENGE-NATIVE-EVIDENCE-AND-CANARY` | defer | Current native Ultimate Flee acceptance is `REC-O10-D05`; old native labels cannot authorize it. |
| `RUNTIME-DECLARATIVE-VERIFIED-FLOW-COMPOSITION` | retain/reuse | Historical composition facts feed canonical route/retirement work; `REC-O12`/`REC-O14` remove duplicate authority without an O11 dependency. |
| `DQ-FLOW-RECRUITMENT` | supersede | Canonical free recruitment is `REC-D07` with independent `REC-O10-D07A`/`REC-O10-D07B` records. |
| `RECRUITMENT-FREE-ATTEMPT-MAINTENANCE` | supersede | Recruitment maintenance is owned by `REC-D07` and its named O10 tier records; old five-window success is reusable evidence only. |
| `DQ-FLOW-NANOWEAPON` | supersede | Canonical Normal Craft route is `REC-R15` with current record `REC-O10-R15`; policy/queue boundaries remain explicit. |
| `NANO-MATERIAL-PRODUCTION-MAINTENANCE` | supersede | Canonical six-hour material maintenance is `REC-R14` with current record `REC-O10-R14`. |
| `DQ-FLOW-ENHANCE-GEAR` | supersede | Canonical Gear route is `REC-R03` with current record `REC-O10-R03`; one-star/quantity boundaries remain explicit. |
| `DQ-FLOW-ENHANCE-CHIP` | supersede | Canonical Chip route is `REC-R04` with current record `REC-O10-R04`; cross-family mismatches deny. |
| `DQ-FLOW-ENHANCE-MODULE` | supersede | Canonical Module route is `REC-R05` with current record `REC-O10-R05`; cross-family mismatches deny. |
| `DQ-FLOW-CAMPAIGN-AP` | supersede | Canonical Campaign AP route is `REC-R11` with current record `REC-O10-R11`; it remains policy/budget gated. |
| `DQ-FLOW-CAMPAIGN-AUTO-BATTLE` | retain/reuse | Historical auto-battle facts feed `REC-R11`/`REC-O10-R11`; no AP spend or current authorization follows. |
| `DQ-FLOW-CAMPAIGN-AUTO-BATTLE-BLUESTACKS` | retain/reuse | Historical BlueStacks auto-battle evidence is replay/provenance input for `REC-O10-R11`, not current native acceptance. |
| `DQ-FLOW-WORLD-STAMINA-ENGINE` | supersede | Canonical World/gathering foundation is `REC-R16` with current record `REC-O10-R16`; stamina is not an implicit spend authority. |
| `DQ-FLOW-ZOMBIE-LAIR` | supersede | Canonical Zombie Lair route is `REC-R19` with current record `REC-O10-R20`; level/stamina/march constraints remain explicit. |
| `ZOMBIE-LAIR-HOME-MAINTENANCE` | defer | Current Lair maintenance remains `REC-O10-R20`; old maintenance scope supplies no native authority. |
| `DQ-FLOW-STAMINA` | defer | Stamina use is considered only within the named `REC-O10-R20` Lair record; it cannot substitute for gathering or authorize refill. |
| `DQ-FLOW-GATHERING` | supersede | Canonical gathering foundation/variants are `REC-O10-R16`, `REC-O10-R17`, and `REC-O10-R18`; each node/material remains independent. |
| `DQ-FLOW-TRAINING` | supersede | Canonical training records are `REC-O10-R06`–`REC-O10-R09`; old aggregate training work cannot authorize a tier. |
| `DQ-FLOW-BUILDING-UPGRADE` | defer | Policy route is `REC-P06`/`REC-O10-P06`; no building spend without a named decision and budget. |
| `DQ-FLOW-TECH-UPGRADE` | defer | Policy route is `REC-P07`/`REC-O10-P07`; no research spend without a named decision and budget. |
| `DQ-FLOW-HERO-UPGRADE` | defer | Policy route is `REC-P04`/`REC-O10-P04`; hero identity/material/cost approval is still absent. |
| `DQ-FLOW-PURCHASES` | defer | Shop/BuyBox scope maps to `REC-P01`–`REC-P03` and `REC-P12`/matching O10 records; no generic purchase authority. |
| `DQ-FLOW-DONATION` | defer | Policy route is `REC-P08`/`REC-O10-P08`; donation remains disabled without an explicit budget. |
| `DQ-FLOW-SPEEDUP` | defer | Policy route is `REC-P09`/`REC-O10-P09`; no universal or premium speedup authority. |
| `DQ-FLOW-CHALLENGES` | defer/reuse | Historical challenge work feeds the named zero-cost Ruins record `REC-O10-R12`; no aggregate challenge enablement. |
| `DQ-FLOW-RUINS-CHALLENGE-BLUESTACKS` | retain/reuse | Historical Ruins success is reusable provenance for `REC-O10-R12`, never current canonical native acceptance. |
| `DQ-FLOW-HERO-DUEL` | defer | Policy route is `REC-P05`/`REC-O10-P05`; PvP remains disabled absent explicit product approval. |

## Later decisions and ambiguity register

These are named decisions for the eventual owners, not questions to the current planning author:

1. Confirm the expected redacted account/server identity tuple, secondary evidence, and strong-check
   TTL for `REC-O03`; credentials and account switching remain manual-only.
2. Confirm the selected Bliss hosted profile and exact fallback rejection triggers in `REC-O02`;
   changing NAS-only deployment requires an explicit user decision, not an inferred exception.
3. For each `REC-O10-*` record, the product owner must name the route budget, ordinary-resource /
   stamina / AP / march / queue reserve, allowed quantity, quiet/reset window, and explicit approval.
   Policy routes `REC-O10-P01` through `REC-O10-P12` remain disabled until their separate decisions.
4. Name the selected D12 qualifying scenario IDs before a routine run; D12 must not depend on O10
   umbrella completion or on prohibited/deferred rows.
5. Set operational disk/evidence quotas, retention tiers, notification channel, maintenance window,
   and outage escalation for `REC-O07` without creating a new authorization source.
6. Set bounded worker/game/runtime/VM restart thresholds and operator escalation for `REC-O06`;
   an Unraid host reboot is never delegated to the worker.
7. Decide whether optional private viewer input is needed for `REC-O04`; unattended service must
   remain independent of it.
8. Define the final selected capability set for `REC-O11`; closure may accept only named routes and
   must list policy-blocked and omitted scope explicitly.
9. Coordinate, but do not review or fetch, the separate cleanup PR; after its owner supplies a
   revision, compare only exact changed paths relevant to owned documents. A source rename/rebase
   mismatch is a checkpoint for coordination, not a global runtime block.
