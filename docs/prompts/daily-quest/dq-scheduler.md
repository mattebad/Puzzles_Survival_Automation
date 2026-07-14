# DQ-SCHEDULER

Repository authority: matrix owns scheduler eligibility; catalog never authorizes scheduling.
`BACKLOG.md` owns this task. Main Quest Claim excluded.

Scope: deterministic offline one-pulse Daily scheduler with persisted task state. Reusable
components: Phase F scheduler, task-state store, runtime integration gate. Route: eligibility
evaluation → one pulse → persisted result. Source recognizer: dormant matrix entry and fresh
game-day identity; target: offline pulse state; successor: deterministic persisted terminal state.

Current-frame binding is required before any future consequential handler. Policy: all scheduler
eligibility false during this run; no resource or transaction dispatch. Postcondition: one pulse
cannot duplicate work, claim, or live state. Recovery: unresolved actions block later pulses.
Daily reconciliation maps selected objective to matrix owner; Claim flows remain independent.

Persistence is offline-only. Tests: one-pulse determinism, lease-free offline behavior, disabled
eligibility, duplicate prevention, stale-day rejection, and schema compatibility. Bliss evidence
is observational; GnBots geometry cannot promote. Future navigation read-only only. Prohibit
ADB, worker/VM lifecycle, leases, journal migration, live task rows, registrations, scheduler
enablement, and gameplay input. Update scheduler docs/matrix. Commit:
`docs(tasks): map every Daily objective to an execution task`. Continue offline autonomously.
