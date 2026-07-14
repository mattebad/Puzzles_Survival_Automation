# DQ-FLOW-BUILDING-UPGRADE

Repository authority: catalog owns `upgrade_building`; matrix owns disabled policy/status; backlog owns task.
Main Quest Claim excluded.

Scope: Vehicle Depot/building-upgrade wording remains distinct from other upgrades. Reuse
building identity and offline route model only. Route: Daily row → building target. Source: row,
building identity, and current level; target: exact upgrade control; successor: level change.
Bind all recognizers to current frame in any future implementation.

Policy: DISABLED_POLICY; no material spend, transaction, registration, scheduler eligibility, or
live input. Postcondition: offline contract proves no dispatch. Recovery: fail closed on ambiguous
building, cost, stale frame, or successor. Daily maps `upgrade_building`; Claim separate.
Persistence dormant.

Tests: Vehicle Depot wording reconciliation, disabled validator, no registry, scheduler false,
offline model, Main negative, Claim separation. Bliss/GnBots cannot override policy. Future
navigation read-only. Update docs/matrix/status. Commit:
`docs(tasks): map every Daily objective to an execution task`. Continue offline.
