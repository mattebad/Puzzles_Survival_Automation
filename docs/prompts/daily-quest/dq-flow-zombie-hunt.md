# DQ-FLOW-ZOMBIE-HUNT

Repository authority: catalog owns `hunt_zombie`; matrix owns disabled policy/status; backlog owns task.
Main Quest Claim excluded.

Scope: Hunt Zombie, distinct from Defeat Zombie Lair. Reuse world/stamina route primitives only.
Route: Daily row → World zombie hunt. Source: row, zombie target, current resource state; target:
exact hunt control; successor: hunt result/progress. Bind source/target/successor to current frame.

Policy: DISABLED_POLICY; no march/combat/resource transaction, registration, scheduler eligibility,
or live input. Postcondition: offline contract proves no dispatch. Recovery: fail closed on target,
route, resource, stale frame, or result ambiguity. Daily maps `hunt_zombie`; Claim independent.
Persistence dormant.

Tests: Hunt-vs-Lair identity, disabled validator, no registry, scheduler false, Main negative, Claim
separation. Bliss/GnBots geometry cannot override policy. Future navigation read-only. Update docs/
matrix/status. Commit: `docs(tasks): map every Daily objective to an execution task`. Continue offline.
