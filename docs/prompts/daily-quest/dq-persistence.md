# DQ-PERSISTENCE

Repository authority: matrix owns persistence integration and promotion; catalog remains
observational. `BACKLOG.md` owns this task. Main Quest Claim is excluded.

Scope: dormant Daily task-state persistence keyed by game-day identity, objective key, and flow.
Reusable components: Phase F task state, safety store, unresolved-action guard. Route: offline
contract → validation → future runtime gate. Source recognizer: current task identity; target:
validated state record; successor: durable read-back. Current-frame binding belongs to future
action flows, not persistence.

Policy: no live rows during planning. Transaction: atomic offline state transition with rollback
on failed write. Postcondition: deterministic idempotent state and no Claim implied by completion.
Recovery: preserve unresolved actions, reject schema mismatch, and fail closed on duplicate keys.
Daily reconciliation maps state to catalog key; Claim remains separate.

Scheduler behavior: dormant and ineligible. Tests: schema-v1/v2 compatibility, game-day identity,
idempotence, unresolved blocking, rollback, no-live-row assertion, and offline replay. Bliss
evidence only supports flow status; GnBots never authorizes state. Future navigation none beyond
read-only fixtures. Prohibit ADB, worker/VM changes, leases, journal migration, live evidence,
runtime registration, scheduler eligibility, and gameplay input. Update persistence contract and
matrix. Commit: `docs(tasks): map every Daily objective to an execution task`. Continue offline.
