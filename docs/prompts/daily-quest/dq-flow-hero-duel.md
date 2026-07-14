# DQ-FLOW-HERO-DUEL

Repository authority: catalog owns `join_hero_duel`; matrix owns disabled policy/status; backlog owns task.
Main Quest Claim excluded.

Scope: Join Hero Duel. Reuse Hero Duel identity and offline eligibility model only. Route: Daily
row → Hero Duel. Source: row and event identity; target: exact join control; successor: participation
state/progress. Bind source/target/successor to current frame.

Policy: DISABLED_POLICY; no event entry, resource transaction, registration, scheduler eligibility,
or live input. Postcondition: offline contract proves no dispatch. Recovery: fail closed on event,
eligibility, stale-frame, or successor ambiguity. Daily maps `join_hero_duel`; Claim independent.
Persistence dormant.

Tests: event identity, disabled validator, no registry, scheduler false, Main negative, Claim
separation. Bliss/GnBots cannot override policy. Future navigation read-only. Update docs/matrix/
status. Commit: `docs(tasks): map every Daily objective to an execution task`. Continue offline.
