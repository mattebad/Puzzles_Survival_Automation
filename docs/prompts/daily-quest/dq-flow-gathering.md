# DQ-FLOW-GATHERING

Repository authority: catalog owns `gather_food`, `gather_wood`, `gather_steel`, `gather_gas`; matrix owns
state/policy; backlog owns task. Main Quest Claim excluded.

Scope: parameterized gathering family. `gather_food` aliases are Gather Food/Gathered Food,
target 30000, format `current/30000`; retain resource variants without semantic merging. Reuse
world/stamina engine, search/node recognizers, safe action core. Route: Daily row → World Search
→ resource node → march. Source: completed row and resource identity; target: exact node/march;
successor: resource progress/inventory. Bind current frame.

Policy: evidence-gated material action. Transaction: one exact dispatch, bounded retry, unresolved
block. Postcondition: requested resource progress confirmed. Recovery: fail closed on node,
resource, march, budget, stale-frame, or successor ambiguity. Daily reconciliation keeps quantity
and identity provenance separate; Claim independent. Persistence/scheduler dormant.

Tests: four-variant family ownership, food quantity/format, node identity, budget guard, replay,
cardinality, successor proof, Main negative, registry false, scheduler false. Bliss-native evidence
required; GnBots geometry never authorizes. Future navigation read-only. Prohibit ADB, worker/VM,
leases, journal migration, live input/evidence, registration, scheduler eligibility. Update docs/
matrix/status. Commit: `docs(tasks): map every Daily objective to an execution task`. Continue offline.
