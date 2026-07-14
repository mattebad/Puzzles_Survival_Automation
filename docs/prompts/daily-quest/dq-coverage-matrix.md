# DQ-COVERAGE-MATRIX

Repository authority: catalog owns reconciled Daily objective identity and evidence; execution
matrix owns current status, policy, promotion, registration, persistence, and scheduler fields;
`BACKLOG.md` owns task ownership. Main Quest Claim is excluded.

Scope: exactly one matrix entry per catalog key, plus typed support flows for selected Daily
inventory, generalized row Claim, milestone Claim, persistence, one-pulse scheduler, and runtime
gate. Include all variants: food/wood/steel/gas gathering, training types, shops, challenges,
Zombie, Hero, Headquarters, and Vehicle Depot wording.

Components: catalog loader, matrix schema, family ownership map. Route: offline cross-document
mapping. Source recognizer: catalog key; target: matrix entry; successor: no live successor.
Current-frame binding is required in future handlers. Policy: every consequential entry gets
resource, transaction, and postcondition fields. No action transaction in this task.

Postcondition: key sets, family sharing, backlog owners, routes, and closed enums are deterministic.
Recovery: fail closed on orphan, duplicate, invalid enum, or authority contradiction. Daily
reconciliation is explicit. Claim readiness is independent from objective completion. Persistence
and scheduler remain dormant, with all eligibility false.

Tests: matrix schema, catalog parity, support-flow exclusion from count, policy/postcondition
presence, registration accuracy, status preservation, and scheduler dormancy. Bliss evidence must
be linked for live status; GnBots geometry cannot authorize promotion. Future navigation is
read-only. Prohibit ADB, leases, journal migration, worker/VM changes, live input, new registration,
and scheduler eligibility. Update matrix docs, backlog, and handoff. Commit:
`docs(tasks): map every Daily objective to an execution task`. Stop on unrepresentable conflict;
otherwise continue offline.
