# DQ-FLOW-ZOMBIE-LAIR

Repository authority: catalog owns `defeat_zombie_lair`; matrix owns policy/status; backlog owns task.
Main Quest Claim excluded.

Scope: Defeat Zombie Lair. Reuse world/stamina engine, Daily inventory, Lair route, safe action
core. Route: Daily row → world → recognized Zombie Lair. Source: completed row, current stamina,
and Lair identity; target: exact Lair action; successor: Lair defeat and row progress. Bind all
to current frame.

Policy: evidence-gated material stamina/action cost. Transaction: one bounded dispatch with
unresolved-action blocking. Postcondition: exact Lair defeat confirmed. Recovery: fail closed on
wrong Lair, stale counter, budget mismatch, or missing successor. Daily maps `defeat_zombie_lair`;
Claim separate. Persistence/scheduler dormant.

Tests: route and resource replay, target identity, budget guard, cardinality, successor proof,
Main negative, registration false, scheduler false. Bliss-native evidence required; GnBots
geometry is provenance only. Future navigation read-only. Prohibit ADB, worker/VM, leases, journal
migration, live input/evidence, registration, scheduler eligibility. Update docs/matrix/status.
Current boundary: `tasks/zombie_lair.py` composes the shared World/stamina primitive for pure
Lair level, march, stamina, and result replay; fresh Bliss-native Lair evidence remains required
for promotion. Commit: `feat(tasks): add Zombie Lair offline contract`. Continue offline.
