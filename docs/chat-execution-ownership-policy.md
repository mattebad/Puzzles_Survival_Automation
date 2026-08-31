# Chat and execution ownership policy

Exactly one chat, agent, worker, collector, or automation may prepare or issue runtime input. Every
live path uses `pnsctl development-session`, which owns the singleton lock for the whole bounded
flow and releases it automatically.

Parallel live-runtime work is prohibited. Offline planning may coexist only when it cannot mutate
the runtime or overlap working-tree ownership.

A handoff occurs only after the session has terminated, native evidence and the compact summary are
flushed, runtime ownership is released, and attributable staged/unstaged paths are known. Routine
inputs, recognition failures, repairs, tests, zoom attempts, combat, claims, rewards, and recovery
do not trigger `CURRENT_HANDOFF.md`, queue, or backlog rewrites. Update those artifacts only at a
flow checkpoint or genuine external blocker.

## Delegated receipt ownership

The parent controller may issue one single-use delegated runtime receipt at a time. A receipt binds
the exact task, flow, Luna identity, clean candidate content fingerprint, HEAD, canonical
`pnsctl development-session` argv, scenario, variant, capability manifest, budgets, expiry, and
result identity. Receipt state is controller-owned durable state; its digest detects alteration but
is not a bearer credential.

Issuance and admission reject dirty or changed candidates. Admission consumes the receipt before
runtime singleton acquisition, so a failed, dry-run, crashed, timed-out, or ambiguous admission
cannot be replayed. Delegated sessions retain receipt-bound results and evidence and release the
singleton on every safe terminal path. All authorized repairs must be complete before final
acceptance. Canary admission requires Luna implementation self-check evidence and final parent Sol
integration acceptance bound to the receipt's final clean candidate content fingerprint. For
`sol_plus_terra`, the required conditional independent read-only Terra review evidence (and its one
recheck when a repair occurred) must be recorded before that final Sol acceptance; Solo cannot
bypass this class-specific gate or admit live work without it. That acceptance is the last
acceptance gate before live admission.
