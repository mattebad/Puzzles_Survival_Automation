# DQ-FLOW-ENHANCE-GEAR

Repository authority: catalog owns `enhance_gear`; matrix owns policy/status; backlog owns task. Main Quest
Claim excluded.

Scope: Gear enhancement, shared with chip/module family only where transaction semantics match.
Reuse Daily inventory, Commander Info enhancement primitives, safe action core. Route: Daily row
→ Commander Info → Gear. Source: completed row and selected gear; target: exact enhance control;
successor: gear level/quality changed. Bind all to current frame.

Policy: evidence-gated material cost. Transaction: one exact enhancement dispatch, bounded retry,
unresolved-action block. Postcondition: selected gear enhancement confirmed. Recovery: fail closed
on selected-item ambiguity, resource mismatch, stale frame, or absent successor. Daily maps
`enhance_gear`; Claim independent. Persistence/scheduler dormant.

Tests: family-ownership boundaries, cost guard, replay, cardinality, successor proof, Main negative,
registration/scheduler dormancy. Bliss-native evidence required; GnBots is provenance only. Future
navigation read-only. Prohibit ADB, worker/VM, leases, journal migration, live input/evidence,
registration, scheduler eligibility. Update docs/matrix/status. Commit:
`docs(tasks): map every Daily objective to an execution task`. Continue offline.
