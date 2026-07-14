# DQ-FLOW-HERO-OWNERSHIP

Repository authority: catalog owns `own_hero`; matrix owns disabled policy/status; backlog owns task. Main
Quest Claim excluded.

Scope: Own Hero, distinct from Upgrade Hero and Hero Duel. Reuse hero identity and offline state
model only. Route: Daily row → Hero roster. Source: row and hero identity; target: exact ownership
state; successor: roster ownership/progress. Bind current frame.

Policy: DISABLED_POLICY; no recruitment/purchase/resource transaction, registration, scheduler
eligibility, or live input. Postcondition: offline contract proves no dispatch. Recovery: fail closed
on hero identity, state, stale frame, or successor ambiguity. Daily maps `own_hero`; Claim separate.
Persistence dormant.

Tests: ownership-vs-upgrade distinction, disabled validator, no registry, scheduler false, Main
negative, Claim separation. Bliss/GnBots cannot override policy. Future navigation read-only.
Update docs/matrix/status. Commit: `docs(tasks): map every Daily objective to an execution task`.
Continue offline.
