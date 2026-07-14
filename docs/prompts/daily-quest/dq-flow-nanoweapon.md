# DQ-FLOW-NANOWEAPON

Repository authority: catalog owns `craft_nanoweapon`; matrix owns status/policy; backlog owns task. Main
Quest Claim excluded.

Scope: Craft nanoweapon. Reuse Daily inventory, nanoweapon route, safe action core, evidence
contract. Route: Daily row → nanoweapon workshop. Source: completed row and valid recipe; target:
exact craft control; successor: item/count/inventory change. Bind current source, target, successor.

Policy: evidence-gated; declare materials and transaction cost before promotion. Transaction:
single exact craft dispatch, bounded retry, unresolved-action block. Postcondition: requested
nanoweapon craft confirmed. Recovery: fail closed on stale frame, recipe/resource ambiguity, or
missing successor. Daily reconciliation maps `craft_nanoweapon`; Claim separate. Persistence/
scheduler dormant.

Tests: offline recipe/resource contract, replay, cardinality, successor proof, Main negative,
registration dormancy, scheduler false. Bliss-native evidence required; GnBots geometry never
authorizes. Future navigation read-only. Prohibit ADB, worker/VM, leases, journal migration, live
input/evidence, registration, scheduler eligibility. Update docs/matrix/status. Commit:
`docs(tasks): map every Daily objective to an execution task`. Continue offline.
