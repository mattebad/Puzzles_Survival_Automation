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
authorizes. Navigation-only capture is permitted under live-test policy; consequential collection
input remains prohibited until game-day, reward-policy, target, transaction, and postcondition gates
pass. No worker/VM changes, lease migration, journal migration, registration, or scheduler
eligibility. Update docs/matrix/status. Commit:
`feat(tasks): bind Daily Supply Depot row`. Current boundary: `tasks/supply_depot.py` plus
`tasks/daily_supply_depot.py` and their focused tests provide pure selected-row replay semantics;
Bliss-native navigation and free-target evidence is retained in
`evidence/sessions/20260714-daily-flow-acquisition/supply-depot-navigation.json`; collection
postcondition and Daily reconciliation remain required. Continue with independent offline work.
