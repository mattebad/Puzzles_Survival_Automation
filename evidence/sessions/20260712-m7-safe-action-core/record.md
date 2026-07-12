# M7-SAFE-ACTION-CORE — Passed

Recorded: 2026-07-12, America/Chicago

## Decision

M7-SAFE-ACTION-CORE Passed. The repository now contains the minimum deterministic safety boundary
for one future supervised quest-to-claim trial. It does not implement or authorize that trial,
the full scheduler, unattended execution, account guard, watchdog, VM lifecycle, or live input.

## Implementation

- Package: `safe_action_core/`.
- SQLite schema version: `1`, with deterministic empty-database migration and rejection of newer
  unknown versions. Test databases use local temporary files.
- Persistent tables: schema version, singleton controller lease, actions, and append-only audit
  events. Every state transition uses `BEGIN IMMEDIATE` transactions.
- Journal: unique action ID and action key; task/action/source/target/frame/profile/day/policy,
  consequence/cost/quantity/postcondition, transport/reconciliation, evidence, timestamps, and
  final status are durable.
- Lifecycle: `prepared → input_sent → confirmed/unresolved`; `cancelled` is limited to positively
  known pre-dispatch outcomes. Invalid transitions and duplicate keys are rejected.
- Lease: one persistent owner with acquisition, heartbeat, expiry, and release. Contention denies;
  expiry is evaluated through an injected clock. Any nonterminal or unresolved consequential
  action blocks a new acquisition or takeover, including the same expired owner.
- Policy: a structured central result is the sole executor authorization path. It requires the
  enabled supervised task, locked RT-019 profile, valid fresh `800x1280` frame, exact source,
  clear overlay, semantic target and in-frame ROI, allowlisted zero-cost R1 consequence, quantity,
  expected postcondition, valid lease, unique key, and no unresolved action.
- Executor: injected capture, transport, post-observation, reconciler, and clock. It persists
  intent before dispatch, mandates a changed fresh immediate recapture and second policy pass,
  calls transport at most once, records dispatch without treating it as success, then requires a
  positive postcondition before confirmation.
- Reconciliation: every persisted `prepared` or `input_sent` record at startup becomes unresolved
  and is never retried. A task-specific reconciler may move unresolved to confirmed only with
  positive evidence; audit history remains append-only.
- Persistence failure after possible dispatch sets a process-global block. The durable prepared
  record remains for startup reconciliation even if the emergency unresolved write also fails.

## Fail-closed results

- RT-019 mismatch and invalid/corrupt/black/resized frames produce global input lock.
- Stale, unknown-source, unknown-overlay, coordinate-only, clipped, ambiguous, malformed ROI,
  unknown consequence/cost/quantity, premium/resource/item/AP/stamina/march/queue/combat/strategic,
  absent lease, duplicate key, and non-enabled task requests deny.
- The six promoted M6 assets match the locked profile. The retained Go negative cannot authorize
  Claim; clipped and ambiguous rows abstain. No production Claim-positive fixture was fabricated.
- Transport exception, dispatch/persistence ambiguity, timeout, unexpected successor, and every
  simulated restart boundary after prepare become unresolved with no automatic replay.

## Verification and independent review

- Final tests: 44 passed, 0 failures, 0 errors.
- M6 corpus validation: 6/6 assets valid and profile-compatible.
- RT-019 manifest/hash validation: passed.
- Compile and whitespace checks: passed.
- Review found no ADB, socket, subprocess, network, credential, scheduler, watchdog, or live-system
  dependency in the new core. Transport is injected and mockable.
- The initial migration test failure and correction are retained in `test-results.md`.

## Criterion decision

All M7-SAFE-ACTION-CORE acceptance criteria passed. No Unraid, Bliss VM, ADB, game, container,
tunnel, runtime network, qcow2, or VM XML access occurred. No live or simulated production asset
was promoted, and no game input occurred.

The next ready task is `MVP-QUEST-TO-CLAIM`. M6 remains In Progress until the later
M6-DQ-TRANSITION-CORPUS task passes.
