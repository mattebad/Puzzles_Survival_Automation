# DQ-CATALOG-RECONCILIATION

Repository authority: `tasks/daily_quest_catalog.json` owns observed Daily objective identity,
aliases, variants, quantities, inventories, and provenance. `tasks/daily_quest_execution_matrix.json`
owns mutable implementation state. `BACKLOG.md` owns task dependencies.

Scope: reconcile every retained Daily inventory name, including `gather_food` (`Gather Food`,
`Gathered Food`, target 30000, `current/30000`), Vehicle Depot, Ultimate Challenge, Hunt Zombie,
Own Hero, and Headquarters attack/win. Classify each as exact key, alias, parameterized variant,
new key, or explicit conflict. Exclude Main Quest Claim.

Components: catalog loader, retained inventories, evidence manifest, provenance records. Route:
offline inventory comparison only. Source/target/successor recognizers: observed-name identity,
canonical key, and no gameplay successor; bind each record to source inventory and current catalog.
Policy: zero-cost offline metadata work; no transaction. Postcondition: deterministic catalog/matrix
key set is complete. Recovery: preserve conflict record and stop reconciliation of that item.

Daily reconciliation: identity and quantity provenance remain separate. Claim: none; reconciliation
never authorizes row or milestone Claim. Persistence/scheduler: dormant; no rows, eligibility, or
registration. Tests: JSON schema, key/count derivation, alias uniqueness, retained-inventory coverage,
and `gather_food` quantity assertions. Bliss evidence: cite retained artifacts only; GnBots is
historical provenance, never authorization.

Future navigation may inspect files and fixtures only. Prohibit ADB, worker/VM changes, leases,
journal migration, live evidence, runtime registration, scheduler enablement, and consequential
input. Update catalog docs and handoff. Commit: `docs(tasks): map every Daily objective to an execution task`.
Stop on irreconcilable evidence conflict; otherwise continue independent offline validation.
