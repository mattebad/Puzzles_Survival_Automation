# DQ-FLOW-HEADQUARTERS-PVP

Repository authority: catalog owns `attack_headquarters_and_win`; matrix owns disabled policy/status; backlog
owns task. Preserve attack-and-win semantics as distinct from Hunt Zombie and Lair. Main Quest
Claim excluded.

Scope: Headquarters attack and win. Reuse world route primitives only. Route: Daily row → enemy
Headquarters. Source: row, Headquarters identity, eligibility; target: exact attack control;
successor: win result and row progress. Bind current source/target/successor frame.

Policy: DISABLED_POLICY; no PvP/combat/resource transaction, registration, scheduler eligibility,
or live input. Postcondition: offline contract proves no dispatch. Recovery: fail closed on target,
eligibility, stale frame, or result ambiguity. Daily maps `attack_headquarters_and_win`; Claim
independent. Persistence dormant.

Tests: attack-vs-win semantics, identity reconciliation, disabled validator, no registry, scheduler
false, Main negative, Claim separation. Bliss/GnBots cannot override policy. Future navigation
read-only. Update docs/matrix/status. Commit: `docs(tasks): map every Daily objective to an execution
task`. Continue offline.
