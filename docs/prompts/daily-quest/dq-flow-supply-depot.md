# DQ-FLOW-SUPPLY-DEPOT

Repository authority: catalog owns `supply_depot`; matrix owns policy/status; backlog owns task. Main Quest
Claim excluded.

Scope: Supply Depot action. Reuse Daily inventory, depot recognizer, safe action core, and free
contract. Route: Daily row → Supply Depot. Source: completed row and depot availability; target:
exact depot control; successor: depot completion/count state. Current-frame bind source/target/
successor.

Policy: evidence-gated; verify zero-cost or declared resource policy before promotion. Transaction:
one exact dispatch, bounded retry, unresolved block. Postcondition: requested depot semantic
confirmed. Recovery: fail closed on stale frame, resource ambiguity, or missing successor.
Daily reconciliation maps `supply_depot`; Claim separate. Persistence/scheduler dormant.

Tests: offline contract replay, cost guard, dispatch cardinality, successor proof, registration
dormancy, and Main negative recognition. Bliss-native evidence required; GnBots geometry never
authorizes. Future navigation read-only. Prohibit ADB, worker/VM, leases, journal migration, live
input/evidence, registration, and scheduler eligibility. Update docs/matrix/status. Commit:
`docs(tasks): map every Daily objective to an execution task`. Continue offline.
